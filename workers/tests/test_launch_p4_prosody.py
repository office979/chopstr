"""Lane P4, Aufgabe 1: prosodische Schnittkanten (``transitions.prosody_edges``) mit synthetischem Audio.

Gemessen wird nur, was sich ohne Hörer messen lässt: das Pegelminimum wird gefunden, der Atem vor dem Wort
bleibt draussen, kein Nachbarwort wird angeschnitten, geschützte Spannen bleiben unberührt. Ob der Schnitt
natürlich klingt, sagt erst ein Hörtest (docs/decisions/040-prosodische-schnittgrenzen.md)."""

from __future__ import annotations

import copy
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import reframe, render_plan, transitions
from chopstr_worker.pipeline.transitions import CutRules, PcmAudio, ProsodyRules

SR = 16000
RULES = CutRules(lead_in_s=0.06, lead_out_s=0.18, min_gap_s=0.1, low_confidence_threshold=0.5)
PROSODY = ProsodyRules(search_window_s=0.35)


def w(text: str, start: float, end: float, speaker: str = "SPEAKER_00", prob: float = 0.95) -> dict:
    return {"text": text, "start": start, "end": end, "speaker": speaker, "prob": prob}


def make_audio(total_s: float, words: list[dict], room: float = 0.01, seed: int = 1) -> np.ndarray:
    """Raumton überall (tiefpassgefiltertes Rauschen wie Lüftung oder Raumhall, kaum Anteil über 2 kHz),
    Sprache (180 Hz mit Obertönen bis 900 Hz) in den Wörtern."""
    rng = np.random.default_rng(seed)
    n = int(total_s * SR)
    noise = np.convolve(rng.normal(0.0, 1.0, n + 31), np.ones(32) / 32.0, mode="valid")[:n]
    x = (noise / max(float(np.std(noise)), 1e-9) * room).astype(np.float32)
    t = np.arange(n) / SR
    for wd in words:
        a, b = int(wd["start"] * SR), int(wd["end"] * SR)
        tt = t[a:b]
        x[a:b] = 0.15 * (np.sin(2 * np.pi * 180 * tt) + 0.5 * np.sin(2 * np.pi * 360 * tt) + 0.3 * np.sin(2 * np.pi * 900 * tt))
    return x


def put(x: np.ndarray, t0: float, t1: float, values: np.ndarray | float) -> None:
    a, b = int(t0 * SR), int(t1 * SR)
    x[a:b] = values if np.isscalar(values) else values[: b - a]


WORDS = [w("Eins", 0.5, 1.0), w("zwei", 1.6, 2.2), w("drei.", 2.8, 3.4)]


def edges_for(segment: dict, words: list[dict], audio, protected=None, rules: ProsodyRules = PROSODY) -> dict:
    padded = transitions.pad_segments([segment], words, RULES)
    return transitions.prosody_edges(padded, words, audio, rules, protected)[0]


# -- Pegelminimum -------------------------------------------------------------------------------------


def test_the_quietest_point_in_the_search_window_becomes_the_cut():
    x = make_audio(4.0, WORDS)
    rng = np.random.default_rng(7)
    put(x, 1.32, 1.38, rng.normal(0, 0.0005, int(0.06 * SR)).astype(np.float32))  # Pegelloch vor „zwei"
    put(x, 2.45, 2.51, rng.normal(0, 0.0005, int(0.06 * SR)).astype(np.float32))  # Pegelloch nach „zwei"
    seg = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, PcmAudio(SR, x))
    e_in, e_out = seg["edges"]["in"], seg["edges"]["out"]
    assert set(e_in) == {"chosen_s", "text_s", "rms_min_s", "breath", "confidence"}
    assert e_in["text_s"] == 1.6 and e_out["text_s"] == 2.2
    # Ein Fenster (20 ms) liegt ganz im Pegelloch, wenn seine Mitte 10 ms vom Rand entfernt ist.
    assert 1.33 - 1e-6 <= e_in["rms_min_s"] <= 1.37 + 1e-6 and 1.33 - 1e-6 <= e_in["chosen_s"] <= 1.37 + 1e-6
    assert 2.46 - 1e-6 <= e_out["rms_min_s"] <= 2.50 + 1e-6 and 2.46 - 1e-6 <= e_out["chosen_s"] <= 2.50 + 1e-6
    assert seg["start"] == e_in["chosen_s"] and seg["end"] == e_out["chosen_s"]
    assert e_in["breath"] is False and e_out["breath"] is False
    assert e_in["confidence"] > 0.9 and e_out["confidence"] > 0.9


def test_in_even_silence_the_edge_stays_where_the_padding_put_it():
    x = make_audio(4.0, WORDS, room=0.0005)
    seg = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, PcmAudio(SR, x))
    padded = transitions.pad_segments([{"start": 1.6, "end": 2.2, "role": "body"}], WORDS, RULES)[0]
    assert abs(seg["start"] - padded["start"]) <= 0.02 and abs(seg["end"] - padded["end"]) <= 0.02


def test_a_breath_right_before_the_word_stays_outside_the_clip():
    x = make_audio(4.0, WORDS, room=0.0003)
    rng = np.random.default_rng(3)
    put(x, 1.30, 1.56, rng.normal(0, 0.02, int(0.26 * SR)).astype(np.float32))  # Atem, 40 ms vor „zwei"
    seg = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, PcmAudio(SR, x))
    e_in = seg["edges"]["in"]
    assert e_in["breath"] is True
    assert 1.0 <= e_in["chosen_s"] <= 1.30
    # Ohne Atem läge die Kante im Vorlauf von 60 ms, also mitten im Atem.
    plain = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, PcmAudio(SR, make_audio(4.0, WORDS, room=0.0003)))
    assert plain["edges"]["in"]["breath"] is False and plain["start"] > 1.30


def test_a_breath_before_the_next_word_ends_the_clip_before_it():
    x = make_audio(4.0, WORDS, room=0.0003)
    rng = np.random.default_rng(4)
    put(x, 2.50, 2.76, rng.normal(0, 0.02, int(0.26 * SR)).astype(np.float32))  # Atem vor „drei"
    seg = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, PcmAudio(SR, x))
    assert seg["edges"]["out"]["breath"] is True and 2.2 < seg["end"] <= 2.50


def test_frames_without_breath_features_are_no_breath():
    frames = [(1.0 + 0.01 * k, 0.05, 0.05) for k in range(30)]  # laut genug, aber ohne Hochfrequenzanteil
    assert transitions.find_breath(frames, 1.31, speech=0.2) is None


def test_neighbour_words_are_never_cut_for_any_gap():
    rng = np.random.default_rng(11)
    for trial in range(60):
        gap_in, gap_out = rng.uniform(0.0, 0.6), rng.uniform(0.0, 0.6)
        words = [w("vor", 0.3, 0.9), w("mitte", 0.9 + gap_in, 1.6 + gap_in), w("nach.", 1.6 + gap_in + gap_out, 2.2 + gap_in + gap_out)]
        words = [{**x, "start": round(x["start"], 3), "end": round(x["end"], 3)} for x in words]
        x = make_audio(3.5, words, room=rng.uniform(0.0002, 0.02), seed=trial)
        if gap_in > 0.1:  # zufälliges Pegelloch irgendwo in der Lücke
            c = words[1]["start"] - rng.uniform(0.02, gap_in)
            put(x, c - 0.02, c + 0.02, 0.0)
        seg = edges_for({"start": words[1]["start"], "end": words[1]["end"], "role": "body"}, words, PcmAudio(SR, x))
        assert words[0]["end"] <= seg["start"] <= words[1]["start"], (trial, seg)
        assert words[1]["end"] <= seg["end"] <= words[2]["start"], (trial, seg)
        plan = {"segments": [{"start": seg["start"], "end": seg["end"], "role": "body"}]}
        assert not [f for f in transitions.check_transitions(plan, words, RULES) if f["type"] == "transition_cut_in_word"]


def test_a_seam_keeps_both_sides_in_their_half_of_the_pause():
    words = [w("a", 0.5, 1.0), w("b", 1.4, 2.0), w("c", 2.6, 3.0)]
    x = make_audio(3.5, words, room=0.0005)
    put(x, 1.05, 1.08, 0.0)  # leisester Punkt in der linken Hälfte der Naht
    segs = transitions.pad_segments([{"start": 0.5, "end": 1.0, "role": "body"}, {"start": 1.4, "end": 2.0, "role": "body"}], words, RULES)
    out = transitions.prosody_edges(segs, words, PcmAudio(SR, x), PROSODY)
    mid = 1.2
    assert out[0]["end"] <= mid + 1e-6 <= out[1]["start"] + 1e-6


def test_protected_spans_are_never_touched():
    x = make_audio(4.0, WORDS)
    put(x, 1.32, 1.38, 0.0)
    seg = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, PcmAudio(SR, x), protected=[(1.25, 1.45)])
    assert not 1.25 - 0.01 < seg["start"] < 1.45 + 0.01


def test_without_audio_the_padding_stays_and_the_edge_says_so():
    seg = edges_for({"start": 1.6, "end": 2.2, "role": "body"}, WORDS, None)
    padded = transitions.pad_segments([{"start": 1.6, "end": 2.2, "role": "body"}], WORDS, RULES)[0]
    assert (seg["start"], seg["end"]) == (padded["start"], padded["end"])
    assert seg["edges"]["in"]["rms_min_s"] is None and seg["edges"]["in"]["confidence"] is None


def test_wav_reader_matches_memory_audio(tmp_path):
    x = make_audio(2.0, WORDS[:1])
    path = tmp_path / "audio16k.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    wav = transitions.WavAudio(path)
    a, b = wav.read(0.5, 0.7), PcmAudio(SR, x).read(0.5, 0.7)
    assert wav.sr == SR and len(a) == len(b) and float(np.max(np.abs(a - b))) < 1e-3
    assert len(wav.read(1.9, 5.0)) == int(0.1 * SR)  # über das Ende hinaus: nur, was da ist


# -- Policy, Schalter, Plan -----------------------------------------------------------------------------


def policy_with(changes: dict[str, object], version: int = 2) -> editorial.Policy:
    """Fassung 2 mit geänderten Werten (Pfad mit Punkten zu Wert), ohne Datei."""
    base = editorial.load(version)
    raw = copy.deepcopy(base.roh)
    for path, value in changes.items():
        node = raw
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return editorial.Policy(version=base.version, stand=base.stand, roh=raw)


def use_policy(tmp_path: Path, monkeypatch, changes: dict[str, object]) -> None:
    """Fassung 2 mit Änderungen als Datei (für Code, der ``editorial.load()`` selbst ruft)."""
    import yaml

    target = tmp_path / "editorial"
    shutil.copytree(editorial.policy_dir(), target)
    raw = copy.deepcopy(editorial.load(2).roh)
    for path, value in changes.items():
        node = raw
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    (target / "clip_policy_v2.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("EDITORIAL_DIR", str(target))
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    editorial.clear_cache()


@pytest.fixture(autouse=True)
def _fresh_policy_cache():
    editorial.clear_cache()
    yield
    editorial.clear_cache()


def test_rules_are_off_by_default_and_need_padding():
    assert transitions.prosody_rules(editorial.load(1)) is None
    assert transitions.prosody_rules(editorial.load(2)) is None  # Regel cut.prosody.enabled steht auf false
    assert "cut.prosody" in editorial.V2_IMPLEMENTED_SWITCHES
    on = policy_with({"cut.prosody.enabled": True})
    assert transitions.prosody_rules(on) == ProsodyRules(search_window_s=0.35)
    assert transitions.prosody_rules(policy_with({"cut.prosody.enabled": True, "implementation.cut.prosody": False})) is None
    assert transitions.prosody_rules(policy_with({"cut.prosody.enabled": True, "cut.padding": False})) is None
    with pytest.raises(editorial.PolicyError, match="search_window_s"):
        transitions.prosody_rules(policy_with({"cut.prosody.enabled": True, "cut.prosody.search_window_s": 0}))
    for leaf in ("cut.prosody.enabled", "cut.prosody.search_window_s"):
        assert leaf in editorial.rule_paths(on.roh) and on.roh["origins"][leaf]["origin"] in ("H", "R")


def _plan(policy: editorial.Policy, audio=None) -> dict:
    rf = reframe.ReframeResult("neutral", "none", False, [], [reframe.Shot(1.5, 2.4, 0, 0, 202, 360)], 640, 360, 1080, 1920)
    return render_plan.build_plan(
        platform="tiktok", segments=[{"start": 1.6, "end": 2.2, "role": "body"}], reframe_result=rf,
        caption_preset="tiktok_words", caption_cards=1,
        sources={"storage_key": "k", "transcript_version": 1, "hook_version": 1, "candidate_id": "c"},
        policy=policy, words=WORDS, audio=audio,
    )  # fmt: skip


def test_plan_carries_edges_only_with_the_rule_and_stays_unchanged_without():
    x = make_audio(4.0, WORDS)
    put(x, 1.32, 1.38, 0.0)
    off = _plan(editorial.load(2), PcmAudio(SR, x))
    assert all("edges" not in e for e in off["timeline"])
    assert off == _plan(editorial.load(2), None)  # ohne Regel spielt das Audio keine Rolle
    on = _plan(policy_with({"cut.prosody.enabled": True}), PcmAudio(SR, x))
    edge = on["timeline"][0]["edges"]["in"]
    assert on["segments"][0]["start"] == edge["chosen_s"] == on["timeline"][0]["source_in"]
    assert render_plan.plan_hash(on, 1, 1) != render_plan.plan_hash(off, 1, 1)
    # Reframe und Captions schneiden dieselben Kanten wie der Plan.
    segs = render_plan.cut_segments([{"start": 1.6, "end": 2.2, "role": "body"}], WORDS, policy_with({"cut.prosody.enabled": True}), PcmAudio(SR, x))
    assert segs == on["segments"]
