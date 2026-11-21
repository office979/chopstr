"""T2 S5: Gold-Set gold_clip_v1, Schema und Validator mit der synthetischen Fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from eval.gold import validate

FIXTURE = Path(__file__).resolve().parents[1] / "eval" / "gold" / "fixtures" / "synthetic_v1.json"


def clips() -> list[dict]:
    return validate.load_set(FIXTURE)


def test_schema_is_valid_json_and_named():
    schema = validate.load_schema()
    assert schema["title"] == "gold_clip_v1"
    assert schema["properties"]["rights"] == {"const": "metadata_only"}


def test_synthetic_fixture_is_valid_with_completeness():
    rep = validate.validate_set(clips())
    assert rep["clips"] == 3 and rep["valid"] == 3
    by_id = {r["id"]: r for r in rep["results"]}
    assert by_id["synth-fehler-preis"]["ready_for_compare"] is True
    assert by_id["synth-fehler-preis"]["completeness"] > 0.9
    assert by_id["synth-ohne-fundstelle"]["ready_for_compare"] is False
    assert "source.start_s" in by_id["synth-ohne-fundstelle"]["missing_core"]
    assert by_id["synth-andersrum"]["completeness"] < by_id["synth-fehler-preis"]["completeness"]


def test_validator_catches_schema_and_domain_errors():
    good = clips()[0]
    cases = {
        "rights": ({**good, "rights": "full"}, "rights"),
        "tier": ({**good, "tier": "influencer"}, "tier"),
        "extra": ({**good, "video_file": "x"}, "unbekanntes Feld video_file"),
        "media": ({**good, "clip": {**good["clip"], "url": "https://cdn.example.org/a.mp4"}}, "Mediendatei"),
        "local": ({**good, "source": {**good["source"], "url": "file:///tmp/x"}}, "source.url"),
        "order": ({**good, "source": {**good["source"], "start_s": 30.0, "end_s": 10.0}}, "start_s muss vor end_s"),
        "conf": ({**good, "source": {**good["source"], "confidence": 1.5}}, "confidence"),
        "missing": ({k: v for k, v in good.items() if k != "provenance"}, "Pflichtfeld provenance"),
    }
    for name, (rec, needle) in cases.items():
        res = validate.validate_record(rec)
        assert any(needle in e for e in res["errors"]), (name, res["errors"])
        assert res["ready_for_compare"] is False


def test_duplicate_ids_are_errors():
    a = clips()[0]
    rep = validate.validate_set([a, copy.deepcopy(a)])
    assert rep["valid"] == 0 and all("nicht eindeutig" in " ".join(r["errors"]) for r in rep["results"])


def test_load_set_accepts_list_and_rejects_wrong_version(tmp_path):
    p = tmp_path / "l.json"
    p.write_text(json.dumps(clips()), encoding="utf-8")
    assert len(validate.load_set(p)) == 3
    p.write_text(json.dumps({"version": "gold_clip_v9", "clips": []}), encoding="utf-8")
    try:
        validate.load_set(p)
    except ValueError as exc:
        assert "gold_clip_v9" in str(exc)
    else:
        raise AssertionError("falsche Version nicht erkannt")


def test_stats_counts():
    st = validate.stats(clips())
    assert st["clips"] == 3 and st["tier"] == {"podcast": 2, "own": 1}
    assert st["sources"] == 2 and st["views"]["known"] == 2 and st["length_s"]["min"] == 8.8


def _multi(good: dict, segs, n=None, comp=None) -> dict:
    edits = {**(good["breakdown"].get("edits") or {}), "n_source_segments": n, "compression": comp}
    return {**good, "source": {**good["source"], "segments": segs}, "breakdown": {**good["breakdown"], "edits": edits}}


def test_segments_fields_are_optional_and_backward_compatible():
    good = clips()[0]
    assert "segments" not in good["source"]  # alte Datensätze ohne die neuen Felder bleiben gültig
    assert validate.validate_record(good)["errors"] == []
    assert validate.validate_record(_multi(good, None))["errors"] == []
    s0, s1 = good["source"]["start_s"], good["source"]["end_s"]
    ok = _multi(good, [[s0, s0 + 2.0], [s1 - 3.0, s1]], 2, 2.5)
    res = validate.validate_record(ok)
    assert res["errors"] == [] and res["warnings"] == [] and res["ready_for_compare"] is True
    assert validate.segments(ok) == [(s0, s0 + 2.0), (s1 - 3.0, s1)]


def test_segments_validation_errors():
    good = clips()[0]
    s0 = good["source"]["start_s"]
    cases = {
        "order": (_multi(good, [[s0 + 5.0, s0 + 1.0]]), "Start muss vor Ende"),
        "equal": (_multi(good, [[s0, s0]]), "Start muss vor Ende"),
        "negative": (_multi(good, [[-1.0, 2.0]]), "-1.0 < 0"),
        "short": (_multi(good, [[s0]]), "weniger als 2"),
        "long": (_multi(good, [[s0, s0 + 1, s0 + 2]]), "mehr als 2"),
        "string": (_multi(good, [["a", "b"]]), "Typ"),
        "empty": (_multi(good, []), "weniger als 1"),
        "count": (_multi(good, [[s0, s0 + 1.0]], n=3), "n_source_segments: 3 statt 1"),
        "comp": (_multi(good, None, comp=-0.5), "compression"),
        "nint": (_multi(good, None, n=1.5), "n_source_segments"),
    }
    for name, (rec, needle) in cases.items():
        res = validate.validate_record(rec)
        assert any(needle in e for e in res["errors"]), (name, res["errors"])
        assert res["ready_for_compare"] is False


def test_segment_outside_span_is_warning_not_error():
    good = clips()[0]
    s0, s1 = good["source"]["start_s"], good["source"]["end_s"]
    rec = _multi(good, [[s0, s1], [s1 + 30.0, s1 + 31.0]], 2)  # Quelle 95 s lang, also kein Formfehler
    res = validate.validate_record(rec)
    assert res["errors"] == [] and len(res["warnings"]) == 1 and "außerhalb" in res["warnings"][0]


def test_stats_counts_segments():
    good = clips()[0]
    s0 = good["source"]["start_s"]
    multi = _multi(good, [[s0, s0 + 1.0], [s0 + 5.0, s0 + 6.0]], 2, 3.0)
    single = {**_multi(good, [[s0, s0 + 1.0]], 1, 1.2), "id": "synth-einzeln"}
    st = validate.stats([multi, single, clips()[1]])
    assert st["segments"] == {"known": 2, "multi": 1, "compression_median": 2.1}
