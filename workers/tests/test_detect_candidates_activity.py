"""Activity ``detect_candidates`` mit Fake-DB, lokalem Storage und Heuristik-Provider (kein Netz, kein Modell)."""

from __future__ import annotations

import re

import pytest

from chopstr_worker import config
from chopstr_worker.activities import analyze
from chopstr_worker.pipeline import story_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import ResidencyError
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler mit Zahlen", "exclude": "Werbung", "platform": "linkedin"}


def _use_provider(monkeypatch, fake_context, provider: str, **env):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.reload()
    fake_context.settings = config.settings()


@pytest.fixture
def source(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief=BRIEF, audio_key="audio/x.wav", duration_s=80.0, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    fake_context.store.put_json("derived", analyze.heatmap_key_for("audio/x.wav", True), {"bin_s": 1, "n_bins": 80, "values": [], "seeds": [3, 50]})
    return sid


def test_writes_rows_events_and_status(fake_db, fake_context, source):
    ids = analyze.run_detect_candidates(fake_context, source)
    assert ids and len(ids) == len(fake_db.candidates)
    row = fake_db.candidates[0]
    assert row["source_id"] == source and row["version"] == 1
    assert row["segments"][0]["role"] == "body" and row["start_s"] < row["end_s"]
    assert row["rubric"]["contract"] == "candidates_v1"
    assert set(row["gates"]) == {"standalone", "fidelity", "sentence_boundaries", "verb_bracket", "no_open_loop"}
    assert row["model_id"] == "heuristic-v1" and row["prompt_version"] == "score_clip_v2"
    assert "heuristic_only" in row["risk_flags"]
    assert isinstance(row["why"], str) and row["why"].endswith(".")

    statuses = fake_db.statuses("detect_candidates")
    assert statuses[0] == "started" and statuses[-1] == "finished" and "progress" in statuses
    prog = next(e for e in fake_db.events_for("detect_candidates") if e["status"] == "progress")
    assert re.fullmatch(r"Kapitel 1 von 1 bewertet, \d+ Kandidaten", prog["message"])
    assert prog["progress"] == 1.0
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["candidates"] == len(ids) and fin["chapters"] == 1 and fin["provider"] == "local-heuristic"
    assert fin["model_id"] == "heuristic-v1" and fin["cached"] is False
    assert fin["prompt_versions"] == ["propose_moments_v1", "score_clip_v2", "story_graph_confirm_v1"]
    assert 0 <= fin["gate_passed"] <= fin["candidates"]

    assert [s for _sid, s in fake_db.status_history] == ["scoring", "ready"]
    assert fake_db.sources[source]["status"] == "ready"
    cost = fake_db.job_costs[-1]
    assert cost["job_type"] == "llm_candidates" and cost["provider"] == "local-heuristic" and cost["model_id"] == "heuristic-v1"
    assert cost["llm_input_tokens"] == 0
    assert fake_context.store.exists("derived", fin["key"])


def test_rerun_is_cached_and_keeps_rows_with_verdict(fake_db, fake_context, source, monkeypatch):
    first = analyze.run_detect_candidates(fake_context, source)
    judged = fake_db.candidates[0]
    # Menschliches Urteil: erkennbar an ``verdict_by``. Nur solche Zeilen überleben den zweiten Lauf,
    # die automatisch angenommenen (ohne ``verdict_by``) weichen dem neuen Ergebnis.
    judged["human_verdict"] = "accepted"
    judged["verdict_by"] = "11111111-1111-1111-1111-111111111111"
    judged["verdict_reason"] = None

    def boom(*a, **kw):
        raise AssertionError("zweiter Lauf darf kein LLM aufrufen")

    monkeypatch.setattr(LLM, "structured", boom)
    second = analyze.run_detect_candidates(fake_context, source)
    assert len(second) == len(first)
    assert judged["id"] in [c["id"] for c in fake_db.candidates]
    # Die beurteilte Zeile bleibt, und der neue Kandidat, der dieselbe Stelle noch einmal vorschlaegt,
    # wird NICHT geschrieben. Frueher stand hier len(first) + 1: die Dublette landete in der Liste,
    # und in der Pruefliste sah ein Mensch denselben Moment zweimal. An einer echten Quelle gemessen
    # standen so 17 Kandidaten fuer 11 Clips, darunter fuenf Paare mit exakt derselben Spanne.
    assert len(fake_db.candidates) == len(first)
    spannen = [(round(c["start_s"], 1), round(c["end_s"], 1)) for c in fake_db.candidates]
    assert len(spannen) == len(set(spannen)), f"doppelte Spannen: {spannen}"
    assert not set(second) & set(first)  # neue Zeilen, alte ohne menschliches Urteil sind weg
    assert "" in second, "der uebersprungene Kandidat haelt seinen Platz, damit die Clip-Zuordnung stimmt"
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["cached"] is True and fin["candidates"] == len(first)
    assert fake_db.sources[source]["status"] == "ready"


def test_new_transcript_version_invalidates_cache(fake_db, fake_context, source):
    analyze.run_detect_candidates(fake_context, source)
    key1 = fake_db.events_for("detect_candidates")[-1]["payload"]["key"]
    fake_db.add_transcript_version(source, demo_words())
    analyze.run_detect_candidates(fake_context, source)
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["key"] != key1 and fin["cached"] is False and fin["transcript_version"] == 2


def test_active_policy_version_is_part_of_the_cache_key(fake_db, fake_context, source, monkeypatch):
    """AP0b: Der Schlüssel enthält die aktive Fassung, nicht die Standardfassung. Ein Wechsel auf v2
    rechnet neu, ein Wechsel zurück auf v1 trifft wieder das alte Ergebnis (Rollback ohne Neuberechnung)."""
    from chopstr_worker import editorial

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    key_v1 = fake_db.events_for("detect_candidates")[-1]["payload"]["key"]

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["key"] != key_v1 and fin["cached"] is False
    # Fassung 2 mit implementation.search.payoff_first: der tatsächlich genutzte Vorschlags-Prompt und die Übersicht.
    assert fin["prompt_versions"] == ["propose_moments_v2", "score_clip_v2", "story_graph_confirm_v1", "episode_overview_v1"]
    assert fake_db.candidates
    assert {c["rubric"]["policy_version"] for c in fake_db.candidates} == {"clip_policy_v2"}

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    fin = fake_db.events_for("detect_candidates")[-1]["payload"]
    assert fin["key"] == key_v1 and fin["cached"] is True
    editorial.clear_cache()


def test_runs_without_heatmap(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace(tier="sovereign")
    sid = fake_db.add_source(wid, "uploads/in.mp4", brief=BRIEF)
    fake_db.add_transcript_version(sid, demo_words())
    ids = analyze.run_detect_candidates(fake_context, sid)
    assert ids
    assert fake_db.sources[sid]["status"] == "ready"


def test_residency_error_fails_with_german_message(fake_db, fake_context, source, monkeypatch):
    _use_provider(monkeypatch, fake_context, "openai-us")
    with pytest.raises(ResidencyError):
        analyze.run_detect_candidates(fake_context, source)
    ev = fake_db.events_for("detect_candidates")[-1]
    assert ev["status"] == "failed"
    assert ev["message"].startswith("Kandidatensuche fehlgeschlagen: Anbieter openai-us verarbeitet nicht in der EU")
    assert fake_db.sources[source]["status"] == "failed"
    assert fake_db.candidates == []


def test_missing_model_fails_clearly(fake_db, fake_context, source, monkeypatch):
    _use_provider(monkeypatch, fake_context, "selfhost-eu", SELFHOST_LLM_BASE_URL="https://llm.intern", SELFHOST_LLM_MODEL="")
    with pytest.raises(RuntimeError, match="Kein Sprachmodell"):
        analyze.run_detect_candidates(fake_context, source)
    ev = fake_db.events_for("detect_candidates")[-1]
    assert ev["status"] == "failed" and "LLM_PROVIDER=local-heuristic" in ev["message"]
    assert fake_db.sources[source]["status"] == "failed"


def test_missing_transcript_fails_clearly(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/in.mp4")
    with pytest.raises(RuntimeError, match="Kein Transkript"):
        analyze.run_detect_candidates(fake_context, sid)
    assert fake_db.sources[sid]["status"] == "failed"


# -- Automatische Clips (kein Auswahlschritt mehr) ---------------------------------------------


# Freigaberelevante Behauptung (Zahl mit Währung) und ein Text, der nur das alte, breite Flag auslöst.
CLAIM_TEXT = "[0] (SPEAKER_00) Bei uns hat das im ersten Jahr rund 40.000 Euro gespart."
HARMLESS_TEXT = "[0] (SPEAKER_00) Allerdings hat das gedauert, weil jeder erst lernen musste."
NEUTRAL_TEXT = "[0] (SPEAKER_00) Dann haben wir das Lager neu sortiert."


def _result(
    start: float, end: float, *, gate_passed: bool, risk_flags: list[str], text: str = NEUTRAL_TEXT,
    title_card: str = " Drei Fehler ",
) -> story_engine.CandidateResult:
    """Ein Kandidat mit frei wählbaren Hinweisen und Text, ohne die Story-Engine laufen zu lassen."""
    return story_engine.CandidateResult(
        segments=[{"start": start, "end": end, "role": "body"}],
        start_s=start,
        end_s=end,
        first_sent=0,
        last_sent=1,
        structure="how_to_list",
        rubric={"contract": "candidates_v1", "suggested_title_card": title_card, "scores": {}, "speakers": [], "text": text},
        gates={"standalone": {"passed": gate_passed}, "fidelity": {"passed": True}},
        story_graph_flags=[],
        risk_flags=risk_flags,
        total=6.0,
        gate_passed=gate_passed,
        why="Darum.",
        model_id="heuristic-v1",
        prompt_version="score_clip_v1",
    )


def _fixed_report(monkeypatch, cands: list[story_engine.CandidateResult]) -> None:
    report = story_engine.DetectReport(
        candidates=cands, chapters=1, proposals=len(cands),
        prompt_versions=["propose_moments_v1"], model_id="heuristic-v1", provider="local-heuristic",
    )  # fmt: skip
    monkeypatch.setattr(story_engine, "run", lambda *a, **kw: report)


@pytest.fixture
def branded_source(fake_db, fake_context, monkeypatch):
    """Quelle mit Markenprofil, dessen Standard-Plattform ``tiktok`` ist."""
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, default_platform="tiktok")
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief=BRIEF, audio_key="audio/x.wav", duration_s=80.0, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    return sid


def test_clip_per_candidate_is_created_in_portrait(fake_db, fake_context, branded_source):
    ids = analyze.run_detect_candidates(fake_context, branded_source)
    clips = list(fake_db.clips.values())
    assert len(clips) == len(ids) >= 1
    assert sorted(c["candidate_id"] for c in clips) == sorted(ids)  # je Kandidat genau einer
    for clip in clips:
        assert clip["aspect"] == "9:16"  # immer Hochformat, unabhängig von der Plattform
        assert clip["platform"] == "tiktok" and clip["destination"] == "tiktok"
        assert clip["status"] == "draft" and clip["created_by"] is None
        assert clip["delete_after"] is None  # setzt der Trigger aus Migration 0006
        cand = next(c for c in fake_db.candidates if c["id"] == clip["candidate_id"])
        assert clip["composition"] == cand["segments"]
        blockers = analyze.auto_accept_blockers(
            cand["risk_flags"], cand["rubric"].get("text") or "", cand["rubric"].get("suggested_title_card") or ""
        )
        if blockers:  # AP0a: Behauptung, Humor oder sensibles Thema wartet auf einen Menschen
            assert cand["human_verdict"] is None
            assert cand["verdict_reason"] == analyze.auto_hold_reason(blockers)
        else:
            assert cand["human_verdict"] == "accepted" and cand["verdict_reason"] == analyze.AUTO_VERDICT_REASON
        assert cand["verdict_by"] is None  # kein Mensch beteiligt
    assert fake_db.events_for("detect_candidates")[-1]["payload"]["clips"] == len(ids)


def test_clip_takes_title_card_and_ad_label_from_candidate_and_brief(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, country="DE", default_platform="linkedin")
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, brief={**BRIEF, "is_ad": True}, status="analyzing")
    fake_db.add_transcript_version(sid, demo_words())
    _fixed_report(monkeypatch, [_result(1.0, 20.0, gate_passed=True, risk_flags=[])])

    analyze.run_detect_candidates(fake_context, sid)
    clip = next(iter(fake_db.clips.values()))
    assert clip["title_card"] == "Drei Fehler" and clip["ad_label"] == "Anzeige"
    assert clip["platform"] == "linkedin" and clip["aspect"] == "9:16"  # Plattform aus dem Profil, Format fest


def test_second_run_creates_no_duplicate_clips(fake_db, fake_context, branded_source):
    first = analyze.run_detect_candidates(fake_context, branded_source)
    clips_after_first = {c["id"] for c in fake_db.clips.values()}
    assert len(clips_after_first) == len(first)

    second = analyze.run_detect_candidates(fake_context, branded_source)
    clips = list(fake_db.clips.values())
    assert len(clips) == len(second) == len(first)  # keine Doppel-Clips
    windows = [(c["start_s"], c["end_s"]) for c in fake_db.candidates]
    assert len(windows) == len(set(windows))  # und auch keine Doppel-Kandidaten
    assert {c["candidate_id"] for c in clips} == set(second)


def test_rendered_clip_survives_rerun_without_second_clip(fake_db, fake_context, branded_source):
    analyze.run_detect_candidates(fake_context, branded_source)
    done = next(iter(fake_db.clips.values()))
    done["status"] = "rendered"

    analyze.run_detect_candidates(fake_context, branded_source)
    assert done["id"] in fake_db.clips
    windows = [(fake_db.clips[c]["id"], _cand_window(fake_db, c)) for c in fake_db.clips]
    assert len({w for _cid, w in windows}) == len(windows)  # jedes Fenster genau einmal belegt


def _cand_window(fake_db, clip_id: str) -> tuple[float, float]:
    clip = fake_db.clips[clip_id]
    cand = next(c for c in fake_db.candidates if c["id"] == clip["candidate_id"])
    return round(float(cand["start_s"]), 1), round(float(cand["end_s"]), 1)


def test_candidate_with_hints_gets_a_clip_too(fake_db, fake_context, branded_source, monkeypatch):
    """Gründerentscheidung: auch Kandidaten mit Einwand oder Risikohinweis bekommen einen Clip-Entwurf.
    Ein Einwand an einem Gate (ohne Risikohinweis) hält die automatische Annahme nicht auf."""
    objected = _result(1.0, 20.0, gate_passed=False, risk_flags=["heuristic_only"])
    clean = _result(30.0, 55.0, gate_passed=True, risk_flags=[])
    _fixed_report(monkeypatch, [objected, clean])

    ids = analyze.run_detect_candidates(fake_context, branded_source)
    assert len(ids) == 2 and len(fake_db.clips) == 2
    objected_row = next(c for c in fake_db.candidates if not c["gate_passed"])
    assert objected_row["human_verdict"] == "accepted"
    assert objected_row["verdict_reason"] == analyze.AUTO_VERDICT_REASON
    assert any(c["candidate_id"] == objected_row["id"] for c in fake_db.clips.values())


@pytest.mark.parametrize(
    ("flags", "text", "blockers"),
    [
        (["humor"], HARMLESS_TEXT, ["humor"]),
        (["sensitive_topic"], NEUTRAL_TEXT, ["sensitive_topic"]),
        ([], "", ["claim_unchecked"]),  # leerer Text lässt sich nicht prüfen
        (["humor"], "  ", ["humor", "claim_unchecked"]),
        (["claim"], CLAIM_TEXT, ["claim"]),
        ([], CLAIM_TEXT, ["claim"]),  # die Prüfung hängt am Text, nicht am Flag
        (["heuristic_only", "claim", "sensitive_topic"], CLAIM_TEXT, ["sensitive_topic", "claim"]),
    ],
)
def test_flagged_candidate_gets_draft_clip_but_no_verdict(
    fake_db, fake_context, branded_source, monkeypatch, flags, text, blockers
):
    """AP0a: Humor, sensible Themen und freigaberelevante Behauptungen nimmt nie die Automatik an. Der
    Entwurf entsteht, das Urteil bleibt leer, die Begründung nennt die Blocker, und der lokale Worker
    rendert ihn nicht."""
    from chopstr_worker import local_worker

    flagged = _result(1.0, 20.0, gate_passed=True, risk_flags=flags, text=text)
    clean = _result(30.0, 55.0, gate_passed=True, risk_flags=["heuristic_only"])
    _fixed_report(monkeypatch, [flagged, clean])

    ids = analyze.run_detect_candidates(fake_context, branded_source)
    assert len(ids) == 2 and len(fake_db.clips) == 2
    flagged_row = next(c for c in fake_db.candidates if c["start_s"] == 1.0)
    clean_row = next(c for c in fake_db.candidates if c["start_s"] == 30.0)

    assert flagged_row["human_verdict"] is None and flagged_row["verdict_by"] is None
    assert flagged_row["verdict_at"] is None
    assert flagged_row["verdict_reason"] == (
        f"automatische Freigabe ausgesetzt: {', '.join(blockers)}, menschliche Prüfung nötig"
    )
    flagged_clip = next(c for c in fake_db.clips.values() if c["candidate_id"] == flagged_row["id"])
    assert flagged_clip["status"] == "draft"

    assert clean_row["human_verdict"] == "accepted" and clean_row["verdict_reason"] == analyze.AUTO_VERDICT_REASON

    rows = fake_db.execute(local_worker.SQL_PENDING_CLIPS, (10,)).fetchall()
    assert {str(r[1]) for r in rows} == {clean_row["id"]}


def test_claim_flag_alone_does_not_hold_back_the_candidate(fake_db, fake_context, branded_source, monkeypatch):
    """H2: Das breite Flag ``claim`` aus ``story_graph.claims_in`` (hier wegen „Allerdings“, „weil“ und
    „jeder“) hält die automatische Annahme nicht auf, solange der Text nichts Freigaberelevantes sagt."""
    _fixed_report(monkeypatch, [_result(1.0, 20.0, gate_passed=True, risk_flags=["claim", "heuristic_only"], text=HARMLESS_TEXT)])

    analyze.run_detect_candidates(fake_context, branded_source)
    (row,) = fake_db.candidates
    assert row["risk_flags"] == ["claim", "heuristic_only"]  # risk_flags bleiben, wie sie sind
    assert row["human_verdict"] == "accepted" and row["verdict_reason"] == analyze.AUTO_VERDICT_REASON


def test_auto_accept_blocking_flags_are_the_product_rule():
    assert not hasattr(analyze, "AUTO_ACCEPT_BLOCKING_FLAGS")
    assert analyze.AUTO_ACCEPT_HARD_FLAGS == ("humor", "sensitive_topic")
    assert analyze.auto_accept_blockers(["claim", "heuristic_only", "humor", "humor"], NEUTRAL_TEXT) == ["humor"]
    assert analyze.auto_accept_blockers(["sensitive_topic", "humor"], CLAIM_TEXT) == ["sensitive_topic", "humor", "claim"]
    assert analyze.auto_accept_blockers(["claim"], HARMLESS_TEXT) == []
    assert analyze.auto_accept_blockers(None, "") == ["claim_unchecked"]


def test_title_card_with_a_claim_holds_back_the_candidate(fake_db, fake_context, branded_source, monkeypatch):
    """H2c: Die Titelkarte geht mit dem Clip hinaus; eine Behauptung dort hält die Freigabe auf wie im Text."""
    assert analyze.auto_accept_blockers([], NEUTRAL_TEXT, "40 Prozent mehr Umsatz") == ["claim"]
    assert analyze.auto_accept_blockers([], "", "40 Prozent mehr Umsatz") == ["claim_unchecked", "claim"]
    _fixed_report(monkeypatch, [_result(1.0, 20.0, gate_passed=True, risk_flags=[], title_card="Doppelt so viele Kunden")])

    analyze.run_detect_candidates(fake_context, branded_source)
    (row,) = fake_db.candidates
    assert row["human_verdict"] is None
    assert row["verdict_reason"] == analyze.auto_hold_reason(["claim"])


def test_rerun_drops_held_draft_clips_without_orphans(fake_db, fake_context, branded_source, monkeypatch):
    """Zurückgehaltene Entwürfe weichen beim erneuten Lauf wie die angenommenen; kein Clip bleibt ohne Kandidat."""
    flagged = _result(1.0, 20.0, gate_passed=True, risk_flags=["claim"], text=CLAIM_TEXT)
    clean = _result(30.0, 55.0, gate_passed=True, risk_flags=[])
    _fixed_report(monkeypatch, [flagged, clean])

    analyze.run_detect_candidates(fake_context, branded_source)
    analyze.run_detect_candidates(fake_context, branded_source)
    cand_ids = {c["id"] for c in fake_db.candidates}
    assert len(fake_db.clips) == 2 and len(fake_db.candidates) == 2
    assert all(c["candidate_id"] in cand_ids for c in fake_db.clips.values())


def _held_and_clean_run(fake_db, fake_context, source_id, monkeypatch) -> tuple[dict, dict]:
    """Erster Lauf mit einem zurückgehaltenen und einem angenommenen Kandidaten; liefert Kandidat und Clip
    des zurückgehaltenen."""
    flagged = _result(1.0, 20.0, gate_passed=True, risk_flags=["claim"], text=CLAIM_TEXT)
    clean = _result(30.0, 55.0, gate_passed=True, risk_flags=[])
    _fixed_report(monkeypatch, [flagged, clean])
    analyze.run_detect_candidates(fake_context, source_id)
    held = next(c for c in fake_db.candidates if c["start_s"] == 1.0)
    assert held["human_verdict"] is None and held["verdict_reason"].startswith(analyze.AUTO_HOLD_REASON_PREFIX)
    clip = next(c for c in fake_db.clips.values() if c["candidate_id"] == held["id"])
    return held, clip


def _assert_survived(fake_db, held: dict, clip: dict) -> None:
    assert any(c["id"] == held["id"] for c in fake_db.candidates)
    assert clip["id"] in fake_db.clips
    # kein zweiter Kandidat und kein zweiter Clip für dasselbe Fenster
    assert sum(1 for c in fake_db.candidates if c["start_s"] == 1.0) == 1
    assert sum(1 for c in fake_db.clips.values() if _cand_window(fake_db, c["id"]) == (1.0, 20.0)) == 1
    cand_ids = {c["id"] for c in fake_db.candidates}
    assert all(c["candidate_id"] in cand_ids for c in fake_db.clips.values())


@pytest.mark.parametrize("work", ["review", "edited", "hook", "captions", "guest"])
def test_rerun_keeps_held_draft_with_human_work(fake_db, fake_context, branded_source, monkeypatch, work):
    """M4: Ein zurückgehaltener Entwurf, an dem ein Mensch gearbeitet hat (Prüfstand gesetzt, nach dem
    Anlegen geändert, eigene Hook- oder Untertitelfassung, Gastfreigabe angefragt), bleibt beim Neulauf
    stehen, und mit ihm sein Kandidat."""
    held, clip = _held_and_clean_run(fake_db, fake_context, branded_source, monkeypatch)
    if work == "review":
        clip["review"] = "bereit"
    elif work == "edited":
        clip["updated_at"] = clip["created_at"] + 1
    elif work == "hook":
        fake_db.add_hook_version(clip["id"], spoken_hook="Eigener Einstieg")
    elif work == "captions":
        fake_db.caption_versions.append({"id": "cv-1", "clip_id": clip["id"], "version": 1})
    else:
        fake_db.guest_approvals.append({"id": "ga-1", "clip_id": clip["id"], "decision": None})

    analyze.run_detect_candidates(fake_context, branded_source)
    _assert_survived(fake_db, held, clip)
    assert fake_db.clips[clip["id"]]["status"] == "draft"
    assert len(fake_db.clips) == 2


def test_rerun_drops_untouched_held_draft(fake_db, fake_context, branded_source, monkeypatch):
    held, clip = _held_and_clean_run(fake_db, fake_context, branded_source, monkeypatch)
    analyze.run_detect_candidates(fake_context, branded_source)
    assert clip["id"] not in fake_db.clips
    assert not any(c["id"] == held["id"] for c in fake_db.candidates)
    assert len(fake_db.clips) == 2  # neu angelegt, nicht verdoppelt


@pytest.mark.parametrize("status", ["rendered", "failed", "rendering"])
def test_held_candidate_whose_clip_is_no_longer_draft_survives_rerun(
    fake_db, fake_context, branded_source, monkeypatch, status
):
    """L11: Steht der Clip eines zurückgehaltenen Kandidaten nicht mehr auf ``draft``, überleben Clip
    und Kandidat den Neulauf."""
    held, clip = _held_and_clean_run(fake_db, fake_context, branded_source, monkeypatch)
    clip["status"] = status

    analyze.run_detect_candidates(fake_context, branded_source)
    _assert_survived(fake_db, held, clip)
    assert fake_db.clips[clip["id"]]["status"] == status


def test_human_accepted_formerly_held_candidate_survives_rerun(fake_db, fake_context, branded_source, monkeypatch):
    """L11: Hat ein Mensch den zurückgehaltenen Kandidaten angenommen (Web: Verdict-Route oder Klick auf
    „Video clippen“), trägt er ``verdict_by`` und bleibt beim Neulauf mit seinem Entwurf stehen."""
    held, clip = _held_and_clean_run(fake_db, fake_context, branded_source, monkeypatch)
    held.update(
        human_verdict="accepted",
        verdict_by="user-1",
        verdict_reason=f"angenommen beim Clippen, vorher {held['verdict_reason']}",
    )

    analyze.run_detect_candidates(fake_context, branded_source)
    _assert_survived(fake_db, held, clip)
    row = next(c for c in fake_db.candidates if c["id"] == held["id"])
    assert row["human_verdict"] == "accepted" and row["verdict_by"] == "user-1"


def test_held_clip_enters_the_render_queue_after_human_acceptance(fake_db, fake_context, branded_source, monkeypatch):
    """H1: Der Klick auf „Video clippen“ setzt in der Web-App das Urteil auf accepted (mit ``verdict_by``)
    und den Clip auf ``draft``; danach findet der lokale Worker ihn über ``SQL_PENDING_CLIPS``."""
    from chopstr_worker import local_worker

    held, clip = _held_and_clean_run(fake_db, fake_context, branded_source, monkeypatch)
    pending = {str(r[0]) for r in fake_db.execute(local_worker.SQL_PENDING_CLIPS, (10,)).fetchall()}
    assert clip["id"] not in pending

    held.update(human_verdict="accepted", verdict_by="user-1", verdict_reason="angenommen beim Clippen")
    pending = {str(r[0]) for r in fake_db.execute(local_worker.SQL_PENDING_CLIPS, (10,)).fetchall()}
    assert clip["id"] in pending


def test_platform_falls_back_to_reels_without_brand_profile(fake_db, fake_context, monkeypatch):
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    brief = {k: v for k, v in BRIEF.items() if k != "platform"}
    sid = fake_db.add_source(wid, "uploads/in.mp4", brief=brief, status="analyzing")  # kein brand_profile_id
    fake_db.add_transcript_version(sid, demo_words())

    ids = analyze.run_detect_candidates(fake_context, sid)
    assert ids and fake_db.clips
    for clip in fake_db.clips.values():
        assert clip["platform"] == "reels" and clip["destination"] == "reels"
        assert clip["aspect"] == "9:16"


def test_platform_comes_from_the_brief_without_brand_default(fake_db, fake_context, monkeypatch):
    """M3: Reihenfolge wie in der Web-App (Markenprofil, Briefing, ``reels``); das Format bleibt 9:16."""
    _use_provider(monkeypatch, fake_context, "local-heuristic")
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/in.mp4", brief=BRIEF, status="analyzing")  # Briefing: linkedin
    fake_db.add_transcript_version(sid, demo_words())

    analyze.run_detect_candidates(fake_context, sid)
    assert {(c["platform"], c["destination"], c["aspect"]) for c in fake_db.clips.values()} == {
        ("linkedin", "linkedin", "9:16")
    }


def test_brand_default_platform_wins_over_the_brief(fake_db, fake_context, branded_source):
    analyze.run_detect_candidates(fake_context, branded_source)  # Marke: tiktok, Briefing: linkedin
    assert {c["platform"] for c in fake_db.clips.values()} == {"tiktok"}


def test_platform_falls_back_to_brief_when_profile_has_no_default(fake_db, fake_context, source):
    """Markenprofil ohne ``default_platform`` (Fake-Profil der Fixture): es gilt das Briefing (linkedin)."""
    analyze.run_detect_candidates(fake_context, source)
    assert {c["platform"] for c in fake_db.clips.values()} == {"linkedin"}


def test_platform_falls_back_to_reels_when_neither_profile_nor_brief_name_one(fake_db, fake_context, source):
    fake_db.sources[source]["brief"] = {k: v for k, v in BRIEF.items() if k != "platform"}
    analyze.run_detect_candidates(fake_context, source)
    assert {c["platform"] for c in fake_db.clips.values()} == {"reels"}


def test_temporal_activity_creates_the_clips_too(fake_db, fake_context, branded_source):
    """Beide Wege laufen durch ``run_detect_candidates``: der lokale Worker direkt, Temporal über die
    Activity ``detect_candidates``. Deshalb hängt die Clip-Erzeugung nur an dieser einen Stelle."""
    ids = analyze.detect_candidates(branded_source)  # Activity-Einstieg, Kontext kommt aus der Fixture
    assert ids and len(fake_db.clips) == len(ids)
    assert {c["aspect"] for c in fake_db.clips.values()} == {"9:16"}


def test_local_worker_picks_up_the_auto_clips(fake_db, fake_context, branded_source, monkeypatch):
    """Die Warteschlange des Renderers (draft + angenommener Kandidat) ist ohne Zutun gefüllt, aber nur
    mit den automatisch angenommenen Kandidaten; zurückgehaltene warten auf einen Menschen (AP0a)."""
    from chopstr_worker import local_worker

    _fixed_report(monkeypatch, [
        _result(1.0, 20.0, gate_passed=True, risk_flags=["heuristic_only"]),
        _result(30.0, 55.0, gate_passed=True, risk_flags=[]),
        _result(60.0, 80.0, gate_passed=True, risk_flags=["claim", "heuristic_only"], text=CLAIM_TEXT),
    ])  # fmt: skip
    ids = analyze.run_detect_candidates(fake_context, branded_source)
    assert len(ids) == len(fake_db.clips) == 3
    accepted = {c["id"] for c in fake_db.candidates if c["human_verdict"] == "accepted"}
    assert len(accepted) == 2
    rows = fake_db.execute(local_worker.SQL_PENDING_CLIPS, (10,)).fetchall()
    assert {str(r[1]) for r in rows} == accepted
    assert {r[2] for r in rows} == {"tiktok"}


def test_finished_payload_names_the_nlp_status(fake_db, fake_context, source, monkeypatch):
    """AP3: unter Fassung 2 steht im finished-Event, wie die Verbklammer geprüft wurde; unter Fassung 1 null."""
    from chopstr_worker import editorial
    from chopstr_worker.pipeline import dach_nlp

    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    assert fake_db.events_for("detect_candidates")[-1]["payload"]["nlp_status"] is None

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    assert fake_db.events_for("detect_candidates")[-1]["payload"]["nlp_status"] == "heuristic"
    editorial.clear_cache()


def test_cache_key_under_v1_is_the_key_before_ap2(monkeypatch):
    """Unter Fassung 1 kommen weder Richtlinien-Hash noch nlp_status in den Schlüssel: gleiche Parameter
    wie vor AP2, also trifft ein Rollback die vorhandenen Ergebnisse."""
    from chopstr_worker import editorial, storage

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    args = ("tv1", 3, dict(BRIEF), ["propose_moments_v1", "score_clip_v2", "story_graph_confirm_v1"], "local-heuristic", "m", {"hook": 1.0})
    before = storage.derived_key(
        "transcript/tv1",
        {
            "transcript_version": 3, "brief": dict(BRIEF), "prompt_versions": args[3], "provider": "local-heuristic",
            "model": "m", "weights": {"hook": 1.0}, "engine": story_engine.ENGINE_VERSION, "policy": "clip_policy_v1",
        },
        story_engine.CONTRACT, "json", prefix="candidates",
    )  # fmt: skip
    assert analyze.candidates_key_for(*args) == before
    editorial.clear_cache()


def test_cache_key_under_v2_follows_policy_content_and_nlp_status(monkeypatch, tmp_path):
    import shutil

    from chopstr_worker import editorial
    from chopstr_worker.pipeline import dach_nlp

    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    args = ("tv1", 3, dict(BRIEF), ["propose_moments_v1"], "local-heuristic", "m", {"hook": 1.0})
    key = analyze.candidates_key_for(*args)

    for name in ("clip_policy_v1.yaml", "clip_policy_v2.yaml"):
        shutil.copy(editorial.policy_dir() / name, tmp_path / name)
    with (tmp_path / "clip_policy_v2.yaml").open("a", encoding="utf-8") as f:
        f.write("\n# Kommentar ändert den Inhalt\n")
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    editorial.clear_cache()
    assert analyze.candidates_key_for(*args) != key

    monkeypatch.delenv("EDITORIAL_DIR")
    editorial.clear_cache()
    monkeypatch.setattr(dach_nlp, "nlp", lambda: object())
    assert analyze.candidates_key_for(*args) != key
    editorial.clear_cache()


# -- AP9-Vorgriff: Heatmap und Signale im Schlüssel, nur unter Fassung 2 ---------------------------------


def _key(heat):
    return analyze.candidates_key_for("tv1", 1, BRIEF, ["propose_moments_v1"], "local-heuristic", "heuristic-v1", {"hook": 1.0}, heat)


def test_cache_key_under_v1_ignores_the_heatmap(monkeypatch):
    from chopstr_worker import editorial

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    base = analyze.candidates_key_for("tv1", 1, BRIEF, ["propose_moments_v1"], "local-heuristic", "heuristic-v1", {"hook": 1.0})
    assert _key(None) == base
    assert _key({"seeds": [3], "audio_values": [0.1]}) == base, "unter v1 bleibt der Schlüssel unverändert"
    editorial.clear_cache()


def test_cache_key_under_v2_contains_heatmap_hash_signals_and_engine_v5(monkeypatch):
    from chopstr_worker import editorial, storage

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    seen = []
    real = storage.derived_key

    def spy(base, params, *a, **kw):
        seen.append(params)
        return real(base, params, *a, **kw)

    monkeypatch.setattr(storage, "derived_key", spy)
    a = _key({"seeds": [3], "audio_values": [0.1, 0.2]})
    b = _key({"seeds": [4], "audio_values": [0.1, 0.2]})
    c = _key({"seeds": [3], "audio_values": [0.1, 0.3]})
    assert len({a, b, c}) == 3, "andere Seeds oder anderer Audioanteil ergeben einen anderen Schlüssel"
    assert _key({"seeds": [3], "audio_values": [0.1, 0.2]}) == a
    params = seen[0]
    assert params["engine"] == story_engine.ENGINE_VERSION_V2 == "story_engine_v5"
    assert params["signals"] == analyze.SIGNALS_VERSION
    assert params["heat_sha256"] == analyze.heat_hash({"seeds": [3], "audio_values": [0.1, 0.2]})
    assert "policy_sha256" in params and "nlp_status" in params
    assert _key(None) != a and seen[-1]["heat_sha256"] is None
    editorial.clear_cache()


def test_v1_report_keeps_engine_v4_and_v2_reports_v5(fake_db, fake_context, source, monkeypatch):
    from chopstr_worker import editorial

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    key = fake_db.events_for("detect_candidates")[-1]["payload"]["key"]
    assert fake_context.store.get_json("derived", key)["engine"] == "story_engine_v4"
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()
    analyze.run_detect_candidates(fake_context, source)
    key = fake_db.events_for("detect_candidates")[-1]["payload"]["key"]
    data = fake_context.store.get_json("derived", key)
    assert data["engine"] == "story_engine_v5"
    assert data["clip_candidates"] and all(cc["contract"] == "clip_candidate_v1" for cc in data["clip_candidates"])
    editorial.clear_cache()
