"""T2 Stufe 0: multimodaler Szenen-Scan, lokaler Fallback, Einspeisung in Heatmap und Kapiteltext. Ohne Netz."""

from __future__ import annotations

from pathlib import Path

import pytest

from chopstr_worker import config, costlog, editorial, providers_mm
from chopstr_worker.pipeline import mm_scan, payoff_search
from chopstr_worker.pipeline.segment import Sentence, numbered
from chopstr_worker.result_cache import ResultCache


def words_two_speakers() -> list[dict]:
    return [
        {"text": "Das", "start": 0.0, "end": 0.3, "speaker": "A"},
        {"text": "ist", "start": 0.3, "end": 0.6, "speaker": "A"},
        {"text": "lustig.", "start": 0.6, "end": 1.0, "speaker": "A"},
        {"text": "(lacht)", "start": 1.1, "end": 1.8, "speaker": "B"},
        {"text": "Stimmt.", "start": 2.0, "end": 2.5, "speaker": "B"},
    ]


@pytest.fixture
def fake_downscale(monkeypatch, tmp_path):
    made: list[tuple[float, float]] = []

    def _fake(video, out_dir, t0, t1, fps, height):
        made.append((t0, t1))
        p = Path(out_dir) / f"w_{t0}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    monkeypatch.setattr(mm_scan, "downscale_window", _fake)
    return made


def test_windows_cover_duration_with_overlap():
    assert mm_scan.windows(1500, 600, 20) == [(0.0, 600.0), (580.0, 1180.0), (1160.0, 1500.0)]
    assert mm_scan.windows(0, 600, 20) == []


def test_normalize_makes_absolute_and_drops_garbage():
    raw = {"events": [
        {"t_start": 5, "t_end": 7, "type": "laughter", "intensity": 1.4},
        {"t_start": 1, "t_end": 2, "type": "explosion", "intensity": 0.5},
        {"t_start": 700, "t_end": 701, "type": "shout", "intensity": 0.5},
        {"t_start": "x", "type": "shout"},
    ]}  # fmt: skip
    out = mm_scan.normalize(raw, 600, 1200, "gemini")
    assert out == [{"t_start": 605.0, "t_end": 607.0, "type": "laughter", "intensity": 1.0, "note": "", "source": "gemini"}]


def test_merge_joins_overlap_duplicates():
    a = {"t_start": 590.0, "t_end": 595.0, "type": "laughter", "intensity": 0.5, "note": "a"}
    b = {"t_start": 594.0, "t_end": 598.0, "type": "laughter", "intensity": 0.9, "note": "b"}
    c = {"t_start": 594.0, "t_end": 598.0, "type": "shout", "intensity": 0.9, "note": "c"}
    out = mm_scan.merge([b, c, a])
    assert len(out) == 2
    laugh = next(e for e in out if e["type"] == "laughter")
    assert (laugh["t_start"], laugh["t_end"], laugh["intensity"]) == (590.0, 598.0, 0.9)


def test_local_events_from_level_speakers_and_asr_marker():
    heat = {"bin_s": 1.0, "audio_values": [0.0, 0.2, 2.8, 2.9, 0.1, 2.1]}
    evs = mm_scan.local_events(words_two_speakers(), heat)
    kinds = [(e["type"], e["t_start"]) for e in evs]
    assert ("shout", 2.0) in kinds and ("emotion_peak", 5.0) in kinds
    assert ("laughter", 1.1) in kinds and ("speaker_change", 1.1) in kinds
    assert all(e["source"] == "local" for e in evs)


def test_scan_without_provider_is_local_fallback():
    res = mm_scan.scan(words_two_speakers(), None, providers_mm.NoneMM(config.Settings()), dict(mm_scan.DEFAULTS))
    assert res["source"] == "local" and any(e["type"] == "laughter" for e in res["events"])


def test_scan_disabled_returns_nothing():
    res = mm_scan.scan(words_two_speakers(), None, None, {**mm_scan.DEFAULTS, "enabled": False})
    assert res["events"] == [] and res["source"] == "off"


def test_policy_switch_on_in_v2_off_in_v1():
    assert mm_scan.settings_from_policy(editorial.load(2))["enabled"] is True
    assert mm_scan.settings_from_policy(editorial.load(2))["provider"] == "none"
    assert mm_scan.settings_from_policy(editorial.load(1))["enabled"] is False


def test_scan_with_mock_provider_uses_cache_on_second_run(tmp_path, fake_downscale):
    mm = providers_mm.MockMM(events=[{"t_start": 650.0, "t_end": 652.0, "type": "applause", "intensity": 0.8}])
    cache = ResultCache(root=tmp_path / "c")
    cfg = dict(mm_scan.DEFAULTS)
    kw = dict(video=tmp_path / "v.mp4", duration_s=1500, work_dir=tmp_path / "w", cache=cache, cache_scope="q1")
    res = mm_scan.scan([], None, mm, cfg, **kw)
    assert res["source"] == "mock" and [e["type"] for e in res["events"]] == ["applause"]
    assert res["events"][0]["t_start"] == 650.0
    assert len(mm.calls) == 3
    res2 = mm_scan.scan([], None, mm, cfg, **kw)
    assert len(mm.calls) == 3  # alles aus dem Cache
    assert {w["status"] for w in res2["windows"]} == {"cached"}
    assert res2["events"] == res["events"]


def test_scan_budget_and_failure_fall_back_per_window(tmp_path, fake_downscale):
    class Boom(providers_mm.MockMM):
        def scan_window(self, *a, **k):
            raise RuntimeError("kaputt")

    words = [{"text": "(lacht)", "start": 700.0, "end": 701.0, "speaker": "A"}]
    res = mm_scan.scan(words, None, Boom(), dict(mm_scan.DEFAULTS), video=tmp_path / "v.mp4", duration_s=1200, work_dir=tmp_path)
    assert res["source"] == "mixed" and {w["status"] for w in res["windows"]} == {"failed"}
    assert [e["type"] for e in res["events"]] == ["laughter"]

    ledger = costlog.RunLedger(budget_tokens=1, s=config.Settings())
    ledger({"stage": "x", "model": "m", "in": 5})
    res = mm_scan.scan(words, None, providers_mm.MockMM(), dict(mm_scan.DEFAULTS), video=tmp_path / "v.mp4", duration_s=1200,
                       work_dir=tmp_path, ledger=ledger)  # fmt: skip
    assert {w["status"] for w in res["windows"]} == {"budget_exhausted"}
    assert res["skipped"] and ledger.skipped[0]["stage"] == "mm_scan"


def test_apply_to_heat_fills_laughter_values_and_seeds_and_payoff_sees_it():
    heat = {"bin_s": 1.0, "n_bins": 200, "seeds": [10], "audio_values": [0.0] * 200}
    events = [
        {"t_start": 100.0, "t_end": 102.0, "type": "laughter", "intensity": 0.9},
        {"t_start": 150.0, "t_end": 150.0, "type": "speaker_change", "intensity": 0.3},
        {"t_start": 30.0, "t_end": 31.0, "type": "shout", "intensity": 0.8},
    ]
    out = mm_scan.apply_to_heat(heat, events)
    assert heat["seeds"] == [10]  # Eingabe unverändert
    assert out["laughter_values"][100] == 0.9 and out["laughter_values"][30] == 0.0
    assert out["event_values"][30] == 0.8
    assert out["seeds"] == [10, 100]  # 30 liegt zu nah an 10, Sprecherwechsel ist kein Seed
    s = payoff_search._S(idx=3, text="Und dann fiel er vom Stuhl.", speaker="A", start=95.0, end=99.6)
    assert payoff_search._laughter_after(out, s) is True
    assert payoff_search._laughter_after(heat, s) is False


def sents() -> list[Sentence]:
    return [
        Sentence(idx=0, text="Er stand auf.", start=0.0, end=2.0, speaker="A", word_range=(0, 2)),
        Sentence(idx=1, text="Dann fiel er hin.", start=2.5, end=4.0, speaker="A", word_range=(3, 6)),
        Sentence(idx=2, text="Unglaublich.", start=6.0, end=7.0, speaker="B", word_range=(7, 7)),
    ]


def test_interleave_puts_pseudo_sentences_without_numbers():
    events = [
        {"t_start": 4.2, "t_end": 5.5, "type": "laughter", "intensity": 0.9},
        {"t_start": 1.0, "t_end": 1.0, "type": "speaker_change", "intensity": 0.3},
        {"t_start": 3.0, "t_end": 3.2, "type": "shout", "intensity": 0.1},
    ]
    text = mm_scan.interleave(sents(), events, lambda s: numbered([s]))
    lines = text.splitlines()
    assert lines[0].startswith("[0]") and lines[1].startswith("[1]")
    assert lines[2].strip() == "[LACHT] (00:04, stark)"
    assert lines[3].startswith("[2]")
    assert "SPRECHERWECHSEL" not in text and "SCHREI" not in text
    # Pseudo-Sätze tragen nie eine Satznummer, die als Schnittkante gewählt werden könnte
    import re

    assert re.findall(r"^\[(\d+)\]", text, re.MULTILINE) == ["0", "1", "2"]


def test_strip_pseudo_removes_markers_from_copy():
    assert mm_scan.strip_pseudo("Er fällt [LACHT] hin [SCHREI (00:03, stark)] wirklich") == "Er fällt hin wirklich"
    assert mm_scan.strip_pseudo("Normale [Klammer] bleibt") == "Normale [Klammer] bleibt"


# -- Einspeisung in die Heatmap-Activity ---------------------------------------------------------------------
def test_heatmap_tag_only_under_policy_v2(monkeypatch):
    from chopstr_worker.activities import analyze

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    assert analyze.mm_scan_tag(config.Settings()) == (None, None)
    assert analyze.heatmap_key_for("audio/x.wav", True) == analyze.heatmap_key_for("audio/x.wav", True, None)
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    tag, cfg = analyze.mm_scan_tag(config.Settings())
    assert tag == "mm_scan_v1:none" and cfg["enabled"] is True
    assert analyze.heatmap_key_for("audio/x.wav", True, tag) != analyze.heatmap_key_for("audio/x.wav", True)
    tag, cfg = analyze.mm_scan_tag(config.Settings(mm_provider="mock"))
    assert tag == "mm_scan_v1:mock"


def test_mm_enrich_without_provider_writes_local_events(fake_context):
    from chopstr_worker.activities import analyze

    src = {"workspace_id": "w", "tier": "standard", "audio_key": "audio/x.wav", "duration_s": 3.0}
    payload = {"bin_s": 1.0, "n_bins": 3, "values": [0, 0, 0], "seeds": [], "laughter_values": [], "audio_values": [0.0, 0.0, 0.0]}
    out = analyze._mm_enrich(fake_context, src, "s1", words_two_speakers(), payload, dict(mm_scan.DEFAULTS))
    assert out["mm_scan"]["source"] == "local"
    assert out["laughter_values"][1] == 0.6
    assert any(e["type"] == "laughter" for e in out["events"])
    assert payload["laughter_values"] == []  # Eingabe unverändert


def test_mm_enrich_falls_back_when_gemini_not_allowed(fake_context):
    from chopstr_worker.activities import analyze

    src = {"workspace_id": "w", "tier": "standard", "audio_key": "audio/x.wav", "duration_s": 3.0, "proxy_key": "proxy/x.mp4"}
    cfg = dict(mm_scan.DEFAULTS, provider="gemini")
    out = analyze._mm_enrich(fake_context, src, "s1", words_two_speakers(), {"bin_s": 1.0}, cfg)
    assert out["mm_scan"]["provider"] == "none" and out["mm_scan"]["source"] == "local"
