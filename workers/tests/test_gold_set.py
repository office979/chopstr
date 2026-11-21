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
