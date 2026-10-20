"""Lane P4, Aufgaben 5 und 6: Export als Abnahmeobjekt (Regel 16), Tonregel 10, Titelkarte als Reparatur.

Die Activity-Tests rendern mit echtem ffmpeg (Fake-DB, lokaler Speicher, Heuristik-Provider)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from chopstr_worker import editorial, ingest
from chopstr_worker.activities import common
from chopstr_worker.activities import render as act_render
from chopstr_worker.pipeline import ausgabe_pruefung, compose, musik, reframe, render, render_plan
from tests.conftest import FakeCursor, make_test_video, requires_ffmpeg
from tests.test_launch_p4_prosody import policy_with, use_policy
from tests.test_render_activity import SEGMENTS, project  # noqa: F401  (Fixture)

# -- Abnahme an Zahlen ---------------------------------------------------------------------------------

TIMELINE = [
    {"segment_index": 0, "role": "body", "source_in": 10.0, "source_out": 13.0, "output_in": 0.0, "output_out": 3.0},
    {"segment_index": 1, "role": "body", "source_in": 20.0, "source_out": 22.0, "output_in": 3.0, "output_out": 5.0},
]
SOURCE = [
    {"text": "Eins", "start": 10.2, "end": 10.6}, {"text": "zwei.", "start": 11.0, "end": 12.8},
    {"text": "Drei", "start": 20.1, "end": 20.5}, {"text": "vier.", "start": 20.8, "end": 21.9},
    {"text": "weg", "start": 15.0, "end": 15.4},
]  # fmt: skip
OUT = compose.remap_words(SOURCE, compose.Composition.from_json([{"start": 10.0, "end": 13.0}, {"start": 20.0, "end": 22.0}]), by_midpoint=True)
SRT = "1\n00:00:00,200 --> 00:00:02,800\nEins zwei.\n\n2\n00:00:03,100 --> 00:00:04,900\nDrei vier.\n"


def check(**changes) -> dict[str, str]:
    args = {
        "plan": {"timeline": TIMELINE, "segments": []}, "dauer_s": 5.0, "srt_text": SRT, "out_words": OUT,
        "source_words": SOURCE, "hat_ton": True, "lufs": -16.0, "schwarzbilder": [], "toleranz_s": 0.2,
    }  # fmt: skip
    args.update(changes)
    return {b.pruefung: b.ergebnis for b in ausgabe_pruefung.abnahme_pruefen(**args)}


def test_a_clean_export_passes_every_check():
    assert check() == {
        "timeline_dauer": "ok", "untertitel_abdeckung": "ok", "untertitel_zeiten": "ok", "synchron": "ok",
        "ton_stumm": "ok", "bild_schwarz": "ok",
    }  # fmt: skip


@pytest.mark.parametrize(
    ("changes", "failing"),
    [
        ({"dauer_s": 5.5}, {"timeline_dauer"}),
        ({"dauer_s": None}, {"timeline_dauer"}),
        ({"srt_text": SRT.replace("00:00:04,900", "00:00:05,400")}, {"untertitel_abdeckung"}),
        ({"out_words": [{**x, "start": x["start"] + 0.1} for x in OUT]}, {"untertitel_zeiten"}),
        # Ein Wort hinter dem letzten Segment: weder synchron noch aus der Schnittbeschreibung.
        ({"out_words": [*OUT, {"text": "weg", "start": 5.3, "end": 5.6}]}, {"synchron", "untertitel_zeiten"}),
        ({"lufs": -70.0}, {"ton_stumm"}),
        ({"hat_ton": False}, {"ton_stumm"}),
        ({"schwarzbilder": [(0.0, 4.8)]}, {"bild_schwarz"}),
    ],
)
def test_each_defect_fails_its_check(changes, failing):
    res = check(**changes)
    assert {k for k, v in res.items() if v == "fehler"} == failing


def test_captions_from_other_segments_than_the_plan_are_caught():
    other = compose.remap_words(SOURCE, compose.Composition.from_json([{"start": 10.0, "end": 13.0}, {"start": 20.3, "end": 22.0}]), by_midpoint=True)
    assert check(out_words=other)["untertitel_zeiten"] == "fehler"


def test_summary_and_stored_flag():
    ok = ausgabe_pruefung.abnahme_pruefen(
        plan={"timeline": TIMELINE}, dauer_s=5.0, srt_text=SRT, out_words=OUT, source_words=SOURCE, hat_ton=True,
        lufs=-16.0, schwarzbilder=[], toleranz_s=0.2,
    )  # fmt: skip
    summary = ausgabe_pruefung.abnahme_zusammenfassung([*ok, ausgabe_pruefung.abrufbar_befund(True)])
    assert summary["export_ok"] is True and summary["pruefung"] == "abnahme"
    bad = ausgabe_pruefung.abnahme_zusammenfassung([*ok, ausgabe_pruefung.abrufbar_befund(False)])
    assert bad["export_ok"] is False and bad["ergebnis"] == "fehler"
    assert ausgabe_pruefung.export_ok_aus([*ausgabe_pruefung.als_liste(ok), summary]) is True
    assert ausgabe_pruefung.export_ok_aus(ausgabe_pruefung.als_liste(ok)) is False  # ohne Abnahme kein Freigabevermerk
    assert ausgabe_pruefung.export_ok_aus(None) is False


def test_export_rules_are_off_by_default():
    editorial.clear_cache()
    assert ausgabe_pruefung.export_rules(editorial.load(1)) is None
    assert ausgabe_pruefung.export_rules(editorial.load(2)) is None
    assert ausgabe_pruefung.export_rules(policy_with({"export.strict": True})) == {"duration_tolerance_s": 0.2}
    assert ausgabe_pruefung.export_rules(policy_with({"export.strict": True, "implementation.export.strict": False})) is None
    with pytest.raises(editorial.PolicyError, match="duration_tolerance_s"):
        ausgabe_pruefung.export_rules(policy_with({"export.strict": True, "export.duration_tolerance_s": -1}))
    for leaf in ("export.strict", "export.duration_tolerance_s"):
        assert leaf in editorial.rule_paths(editorial.load(2).roh)


# -- Regel 10: Tonkette ---------------------------------------------------------------------------------

SPEECH_FILTERS = {"asetpts", "afade", "concat", "asplit", "amix", "acompressor", "loudnorm", "aresample"}
MUSIC_FILTERS = {"atrim", "asetpts", "apad", "volume", "afade", "sidechaincompress", "amix"}
_STATEMENT = re.compile(r"^((?:\[[^\]]+\])+)(.*?)((?:\[[^\]]+\])*)$")


def speech_path_filters(graph: str, speech_inputs: set[int]) -> tuple[set[str], set[str]]:
    """Filter auf dem Weg der Sprache (ab den Segment-Eingängen bis ``[aout]``) und auf dem Weg der Musik.
    Die Sprache darf ``sidechaincompress`` nur als Auslöser (zweiter Eingang) speisen."""
    speech = {f"{i}:a" for i in speech_inputs}
    used_speech: set[str] = set()
    used_music: set[str] = set()
    for stmt in filter(None, (x.strip() for x in graph.split(";"))):
        m = _STATEMENT.match(stmt)
        assert m, stmt
        ins = re.findall(r"\[([^\]]+)\]", m.group(1))
        outs = re.findall(r"\[([^\]]+)\]", m.group(3))
        names = {part.split("=")[0] for part in m.group(2).split(",") if part}
        if not any(i.endswith(":a") or i in speech or i.startswith(("a", "mus", "spr")) for i in ins):
            continue  # Bildkette
        if names == {"sidechaincompress"}:
            assert ins[0] not in speech and ins[1] in speech, stmt  # Sprache nur als Auslöser
            used_music |= names
            continue
        if any(i in speech for i in ins):
            used_speech |= names
            speech |= set(outs)
        else:
            used_music |= names
    assert "aout" in speech
    return used_speech, used_music


def _plan_for_chain(with_music: bool) -> dict:
    out_w, out_h = 1080, 1920
    shots = [reframe.Shot(1.0, 5.0, 0, 0, 404, 720), reframe.Shot(6.0, 12.0, 0, 0, 404, 720)]
    rf = reframe.ReframeResult("neutral", "none", False, [], shots, 1280, 720, out_w, out_h)
    return render_plan.build_plan(
        platform="tiktok", segments=[{"start": 1.0, "end": 5.0}, {"start": 6.0, "end": 12.0}], reframe_result=rf,
        caption_preset="tiktok_words", caption_cards=1, policy=editorial.load(1),
        sources={"storage_key": "k", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"},
        musik={"quelle": "eigen", "datei": "musik/x.mp3", "ab_s": 0, "lautstaerke_db": -18} if with_music else None,
    )  # fmt: skip


@pytest.mark.parametrize("with_music", [False, True])
@pytest.mark.parametrize("compressor", [False, True])
def test_audio_chain_reads_the_original_and_uses_only_allowed_filters(with_music, compressor):
    plan = _plan_for_chain(with_music)
    n_shots, n_segs = len(plan["shots"]), len(plan["segments"])
    args = render.input_args("/quelle/original.mp4", plan, "/musik/x.mp3" if with_music else None)
    inputs = [args[i + 1] for i, a in enumerate(args) if a == "-i"]
    assert inputs[: n_shots + n_segs] == ["/quelle/original.mp4"] * (n_shots + n_segs)  # kein 16-kHz-WAV, keine Analysespur
    m = musik.lesen(plan["musik"]) if with_music else None
    chain = render.audio_chain(plan, n_shots, "loudnorm=I=-16.0:TP=-1.5:LRA=11.0", compressor, m)
    speech, music_filters = speech_path_filters(chain, set(range(n_shots, n_shots + n_segs)))
    assert speech <= SPEECH_FILTERS, speech - SPEECH_FILTERS
    assert music_filters <= MUSIC_FILTERS, music_filters - MUSIC_FILTERS
    assert {"afade", "loudnorm", "aresample"} <= speech
    assert ("acompressor" in speech) is compressor and ("amix" in speech) is with_music


def test_the_checker_rejects_a_forbidden_speech_filter():
    plan = _plan_for_chain(False)
    chain = render.audio_chain(plan, 2, "loudnorm=I=-16.0", False).replace("[ac]loudnorm", "[ac]highpass=f=200,loudnorm", 1)
    speech, _ = speech_path_filters(chain, {2, 3})
    assert "highpass" in speech and not speech <= SPEECH_FILTERS


# -- Activity: Abnahme, Wiederholung, Abbruch, Original-Ton ----------------------------------------------


@pytest.fixture
def strict(tmp_path, monkeypatch, fake_db):
    use_policy(tmp_path, monkeypatch, {"export.strict": True})
    orig = fake_db.execute

    def execute(sql, params=None):
        q = " ".join(sql.split()).lower()
        if q.startswith("select export_checks from clips where id"):
            c = fake_db.clips.get(params[0])
            return FakeCursor([(c.get("export_checks"),)] if c else [])
        return orig(sql, params)

    monkeypatch.setattr(fake_db, "execute", execute)
    yield
    editorial.clear_cache()


def _mp4s(ctx, clip_id: str) -> list[str]:
    return [k for k in ctx.store.list("derived", f"{act_render.RENDER_PREFIX}/{clip_id}/") if k.endswith(".mp4")]


@requires_ffmpeg
def test_strict_export_is_rendered_only_with_export_ok_and_repeats_create_nothing_new(fake_db, fake_context, project, strict):  # noqa: F811
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    clip = fake_db.clips[clip_id]
    checks = clip["export_checks"]
    summary = checks[-1]
    assert clip["status"] == "rendered" and summary["pruefung"] == "abnahme" and summary["export_ok"] is True, checks
    assert {c["pruefung"] for c in checks} >= {"timeline_dauer", "untertitel_abdeckung", "untertitel_zeiten", "synchron", "ton_stumm", "bild_schwarz", "abrufbar"}
    assert clip["file_key"] and fake_context.store.exists("derived", clip["file_key"])
    n_caps = len(fake_db.caption_versions)
    again = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    assert again == clip_id and len(fake_db.clips) == 1 and _mp4s(fake_context, clip_id) == [clip["file_key"]]
    assert fake_db.events_for(act_render.STEP_RENDER)[-1]["payload"].get("skipped") is True
    assert len(fake_db.caption_versions) == n_caps and fake_db.clips[clip_id]["status"] == "rendered"


@requires_ffmpeg
def test_failed_acceptance_is_never_rendered_and_the_file_is_not_released(fake_db, fake_context, project, strict, monkeypatch):  # noqa: F811
    real_exists = fake_context.store.exists
    monkeypatch.setattr(fake_context.store, "exists", lambda bucket, key: False if key.endswith(".mp4") else real_exists(bucket, key))
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    clip = fake_db.clips[clip_id]
    assert clip["status"] == "failed" and clip["file_key"] is None and clip["export_checks"][-1]["export_ok"] is False
    assert clip["render_error"] == "Die Exportdatei liegt nicht im Speicher. Bitte neu clippen."
    # Eine Wiederholung prüft neu und wird nicht ``rendered``, solange die Abnahme scheitert.
    act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    assert fake_db.clips[clip_id]["status"] == "failed" and len(fake_db.clips) == 1
    monkeypatch.setattr(fake_context.store, "exists", real_exists)
    act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    assert fake_db.clips[clip_id]["status"] == "rendered" and len(_mp4s(fake_context, clip_id)) == 1


@requires_ffmpeg
def test_an_aborted_render_never_ends_rendered(fake_db, fake_context, project, strict, monkeypatch):  # noqa: F811
    def broken(*args, **kwargs):
        raise render.RenderError("Rendern fehlgeschlagen: abgebrochen")

    monkeypatch.setattr(act_render.render, "render_from_plan", broken)
    with pytest.raises(render.RenderError):
        act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    (clip,) = fake_db.clips.values()
    assert clip["status"] == "failed" and not clip.get("file_key") and clip["render_error"]


@requires_ffmpeg
def test_render_reads_the_original_even_with_analysis_audio(fake_db, fake_context, project, strict, tmp_path, monkeypatch):  # noqa: F811
    use_policy(tmp_path / "p", monkeypatch, {"cut.prosody.enabled": True, "cut.hook_audio.enabled": True, "export.strict": True})
    wav = ingest.extract_audio(make_test_video(tmp_path / "v.mp4", 14.0), tmp_path / "a16.wav")
    fake_context.store.put_file("derived", common.audio_key_for("uploads/in.mp4"), wav)
    seen: list[tuple[str, dict, str]] = []
    real = render.render_from_plan

    def spy(plan, src_path, *args, **kwargs):
        result = real(plan, src_path, *args, **kwargs)
        seen.append((str(src_path), plan, result.filter_graph))
        return result

    monkeypatch.setattr(act_render.render, "render_from_plan", spy)
    clip_id = act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    (src_path, plan, graph), *_ = seen
    assert Path(src_path).name.startswith("original") and Path(src_path).suffix == ".mp4"
    # Jede Kante trägt ihren Befund; gemessen wird, wo zwischen den Wörtern Raum ist (sonst rms_min_s None).
    edges = [e["edges"][side] for e in plan["timeline"] for side in ("in", "out")]
    assert len(edges) == 2 * len(plan["timeline"]) and any(x["rms_min_s"] is not None for x in edges)
    assert set(plan["hook_audio"]) == {"speech_onset_s", "hook_onset_s", "preamble_removed_s", "ok", "basis"}
    assert plan["hook_audio"]["basis"] == "audio"
    n_shots = len(plan["shots"])
    speech, _ = speech_path_filters(graph, set(range(n_shots, n_shots + len(plan["segments"]))))
    assert speech <= SPEECH_FILTERS
    assert fake_db.clips[clip_id]["export_checks"][-1]["export_ok"] is True
    # Nach dem Rückschreiben der Komposition ergibt ein zweiter Aufruf denselben Plan: nichts Neues.
    act_render.run_render_pack(fake_context, project["cid"], "tiktok")
    assert len(seen) == 1 and fake_db.events_for(act_render.STEP_RENDER)[-1]["payload"].get("skipped") is True


@requires_ffmpeg
def test_repair_title_card_from_the_rubric_reaches_the_plan(fake_db, fake_context, project, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    repair = {"kind": "title_card", "text": "Gilt nur für Betriebe unter 50 Mitarbeitern", "source_span": [12.0, 13.0]}
    cid = fake_db.add_candidate(project["sid"], SEGMENTS, rubric={"suggested_title_card": "Preise im Handwerk", "repair_applied": repair})
    plans: list[dict] = []
    real = render.render_from_plan
    monkeypatch.setattr(act_render.render, "render_from_plan", lambda plan, *a, **k: (plans.append(plan), real(plan, *a, **k))[1])
    act_render.run_render_pack(fake_context, cid, "tiktok")
    assert plans[0]["title_card"] == {"text": repair["text"], "seconds": render_plan.TITLE_CARD_S, "source": "repair", "source_span": [12.0, 13.0]}
    editorial.clear_cache()


def test_repair_title_keeps_the_style_and_is_ignored_under_v1():
    rf = reframe.ReframeResult("neutral", "none", False, [], [reframe.Shot(1.0, 5.0, 0, 0, 404, 720)], 1280, 720, 1080, 1920)
    kw = {
        "platform": "tiktok", "segments": [{"start": 1.0, "end": 5.0}], "reframe_result": rf, "caption_preset": "tiktok_words",
        "caption_cards": 1, "sources": {"storage_key": "k", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"},
    }  # fmt: skip
    repair = {"kind": "title_card", "text": "Nur mit Meisterbrief", "source_span": [1.0, 2.0]}
    fixed = render_plan.build_plan(**kw, policy=editorial.load(2), title_card="Alt", repair=repair)
    manual = render_plan.build_plan(**kw, policy=editorial.load(2), title_card="Nur mit Meisterbrief")
    assert fixed["title_card"]["text"] == "Nur mit Meisterbrief" and fixed["title_card"]["seconds"] == manual["title_card"]["seconds"]
    font = render.font_file()
    caps = {"drawtext": True}
    if font is not None:
        assert render.overlay_filters(fixed, font, caps)[0] == render.overlay_filters(manual, font, caps)[0]
    assert render_plan.build_plan(**kw, policy=editorial.load(1), title_card="Alt", repair=repair)["title_card"] == {"text": "Alt", "seconds": 2.5}
    assert render_plan.repair_title({"kind": "other", "text": "x"}, editorial.load(2)) is None
    assert render_plan.repair_title({"kind": "title_card", "text": "  "}, editorial.load(2)) is None
