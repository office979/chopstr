"""Blindvergleich (AP11, ``eval/blind_compare.py``): Anonymisierung, Seed, Ausgabemenge, Verwerfungsquote, Auswertung."""

from __future__ import annotations

import json
import os
import re

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import dach_nlp
from eval import blind_compare as bc

SUBSET = ("demo_script", "fall_negation_sentence_end", "fall_weak_material", "fall_misrecognized_number_or_name", "fall_near_duplicate_candidates")
VERSION_MARKERS = re.compile(r"\bv[12]\b|clip_policy|policy|fassung|story_engine|candidate_id|cc_[0-9a-f]|heuristi|prompt", re.IGNORECASE)


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    monkeypatch.setattr(dach_nlp, "verb_bracket_available", False)
    yield
    editorial.clear_cache()


def _sources(names=SUBSET):
    return [s for s in bc.fixture_sources() if s["name"] in names]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(dach_nlp, "nlp", lambda: None)
        mp.setattr(dach_nlp, "verb_bracket_available", False)
        out = tmp_path_factory.mktemp("blind")
        bc.generate(_sources(), out, seed=11, k=3)
    editorial.clear_cache()
    return out


def _load(path, name):
    return json.loads((path / bc.FILES[name]).read_text(encoding="utf-8"))


# -- Anonymisierung -------------------------------------------------------------------------------


def _check_sheet(sheet: dict) -> None:
    text = json.dumps(sheet, ensure_ascii=False)
    assert not VERSION_MARKERS.search(text), VERSION_MARKERS.search(text)
    for pair in sheet["paare"]:
        assert set(pair) == {"paar_id", "quelle", "A", "B", "bewertung"}
        for side in ("A", "B"):
            assert set(pair[side]) == {"ausgabe", "text", "segmente", "dauer_s", "hook_gesprochen", "hook_text"}
        assert set(pair["bewertung"]["A"]) == set(bc.CRITERIA) == set(pair["bewertung"]["B"])
        assert pair["bewertung"]["praeferenz"] is None


def test_rating_sheet_carries_no_version(tmp_path):
    """Version, Score, Kandidaten-ID und Begründung stehen im Lauf, nie im Bewertungsbogen."""
    out = _synthetic_dir(tmp_path)
    sheet = _load(out, "sheet")
    assert len(sheet["paare"]) == 4
    _check_sheet(sheet)
    run = (out / bc.FILES["run"]).read_text(encoding="utf-8")
    assert "cc_v1_" in run and "cc_v2_" in run


def test_generated_rating_sheet_carries_no_version(generated):
    _check_sheet(_load(generated, "sheet"))


def test_key_file_holds_the_mapping_separately(generated):
    sheet, key = _load(generated, "sheet"), _load(generated, "key")
    assert set(key["paare"]) == {p["paar_id"] for p in sheet["paare"]}
    for entry in key["paare"].values():
        assert {entry["A"], entry["B"]} == {"v1", "v2"}
    run = _load(generated, "run")
    assert run["quellen"] and "Nicht an die Bewertenden" in run["hinweis"]


def test_output_label_groups_one_version_per_source(generated):
    sheet, key = _load(generated, "sheet"), _load(generated, "key")
    labels: dict[tuple[str, str], set[str]] = {}
    for pair in sheet["paare"]:
        for side in ("A", "B"):
            labels.setdefault((pair["quelle"], key["paare"][pair["paar_id"]][side]), set()).add(pair[side]["ausgabe"])
    assert all(len(v) == 1 for v in labels.values())
    for source in {s for s, _v in labels}:
        assert labels.get((source, "v1")) != labels.get((source, "v2"))


# -- Seed -----------------------------------------------------------------------------------------


def test_fixed_seed_is_reproducible(tmp_path):
    for name in ("a", "b"):
        bc.generate(_sources(), tmp_path / name, seed=11, k=3, switches=False)
    for kind in ("sheet", "key", "rubric"):
        assert (tmp_path / "a" / bc.FILES[kind]).read_bytes() == (tmp_path / "b" / bc.FILES[kind]).read_bytes()


def test_other_seed_changes_order_or_sides():
    runs = {f"q{i}": {"v1": {"angeboten": [_clip(f"a{i}{r}") for r in range(2)]}, "v2": {"angeboten": [_clip(f"b{i}{r}") for r in range(2)]}} for i in range(6)}
    first, _ = bc.make_pairs(runs, seed=1)
    again, _ = bc.make_pairs(runs, seed=1)
    other, _ = bc.make_pairs(runs, seed=2)
    assert first == again
    assert first != other


# -- Ausgabemenge ---------------------------------------------------------------------------------


def _clip(cid: str) -> dict:
    return {"candidate_id": cid, "text": f"Text {cid}.", "segmente": [], "dauer_s": 20.0, "hook": {"gesprochen": "", "text": ""}}


def test_same_output_amount_per_source():
    runs = {
        "q1": {"v1": {"angeboten": [_clip("a1"), _clip("a2"), _clip("a3")]}, "v2": {"angeboten": [_clip("b1")]}},
        "q2": {"v1": {"angeboten": []}, "v2": {"angeboten": [_clip("b2")]}},
        "q3": {"v1": {"angeboten": [_clip("a4"), _clip("a5")]}, "v2": {"angeboten": [_clip("b3"), _clip("b4")]}},
    }
    sheet, key = bc.make_pairs(runs, seed=5)
    per_source = {}
    for entry in key["paare"].values():
        per_source.setdefault(entry["quelle"], []).append((entry["candidate_A"], entry["candidate_B"], entry["rang"]))
    assert {s: len(v) for s, v in per_source.items()} == {"q1": 1, "q3": 2}
    assert ("q1", 1) in {(e["quelle"], e["rang"]) for e in key["paare"].values()}
    pairs_q1 = per_source["q1"][0]
    assert set(pairs_q1[:2]) == {"a1", "b1"}
    assert sorted((s["quelle"], s["version"], s["rang"]) for s in key["nicht_gepaart"]) == [
        ("q1", "v1", 2), ("q1", "v1", 3), ("q2", "v2", 1),
    ]  # fmt: skip
    assert len(sheet["paare"]) == 3


def test_generated_pairs_respect_the_smaller_output(generated):
    run, key = _load(generated, "run"), _load(generated, "key")
    for name, runs in run["quellen"].items():
        n = min(len(runs["v1"]["angeboten"]), len(runs["v2"]["angeboten"]))
        assert len(runs["v1"]["angeboten"]) <= 3 and len(runs["v2"]["angeboten"]) <= 3
        assert sum(1 for e in key["paare"].values() if e["quelle"] == name) == n


# -- Verwerfungsquote -----------------------------------------------------------------------------


def test_rejection_rate_counts_each_reason():
    discarded = [{"reason": "gate"}, {"reason": "gate"}, {"reason": "too_short"}, {"reason": "overlap"}, {}]
    rates = bc.rejection_rates(discarded, proposals=10)
    assert rates == {
        "gate": {"anzahl": 2, "quote": 0.2},
        "overlap": {"anzahl": 1, "quote": 0.1},
        "too_short": {"anzahl": 1, "quote": 0.1},
        "unbekannt": {"anzahl": 1, "quote": 0.1},
    }
    assert bc.rejection_rates([], proposals=0) == {}


def test_rejection_rate_of_a_run_matches_the_report(generated):
    run = _load(generated, "run")
    for runs in run["quellen"].values():
        for r in runs.values():
            assert sum(v["anzahl"] for v in r["verworfen"].values()) == r["verworfen_gesamt"]
            assert r["verworfen_gesamt"] + len([c for c in r["clip_candidates"] if c["decision"] == "accept"]) <= r["vorschlaege"] + len(r["clip_candidates"])


def test_evaluation_sums_rejections_over_sources(tmp_path):
    def run(reasons, proposals):
        return {"vorschlaege": proposals, "verworfen": bc.rejection_rates([{"reason": x} for x in reasons], proposals), "verworfen_gesamt": len(reasons),
                "angeboten": [], "modellaufrufe": 4, "laufzeit_s": 0.5, "quelle_stunden": 0.5, "hooks_mit_befund": 0, "editorial_v1": None}  # fmt: skip

    doc = {
        "provider": "local-heuristic", "k": 5, "gebaute_schalter": [], "varianten": [{"name": "v1", "gruppe": None, "schalter": {}}, {"name": "v2", "gruppe": None, "schalter": {}}],
        "quellen": {"q1": {"v1": run(["gate", "too_long"], 4), "v2": run(["gate"], 4)}, "q2": {"v1": run(["gate"], 6), "v2": run([], 6)}},
    }  # fmt: skip
    (tmp_path / bc.FILES["run"]).write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / bc.FILES["sheet"]).write_text(json.dumps({"paare": []}), encoding="utf-8")
    (tmp_path / bc.FILES["key"]).write_text(json.dumps({"links": "v1", "rechts": "v2", "paare": {}, "nicht_gepaart": []}), encoding="utf-8")
    res = bc.evaluate(tmp_path)
    assert res["varianten"]["v1"]["verworfen"] == {"gate": {"anzahl": 2, "quote": 0.2}, "too_long": {"anzahl": 1, "quote": 0.1}}
    assert res["varianten"]["v1"]["verwerfungsquote"] == 0.3
    assert res["varianten"]["v2"]["verworfen"] == {"gate": {"anzahl": 1, "quote": 0.1}}
    assert res["varianten"]["v1"]["modellaufrufe_je_stunde"] == 8.0
    assert res["varianten"]["v1"]["laufzeit_s_je_stunde"] == 1.0


# -- Auswertung -----------------------------------------------------------------------------------


def _synthetic_run(version: str, n: int, reasons: list[str], passed: bool) -> dict:
    clips = [
        {"candidate_id": f"cc_{version}_{i}", "total": 9.5 - i, "segmente": [{"von_s": 1.0 * i, "bis_s": 30.0 + i, "rolle": "body"}],
         "text": f"Satz {i} der Ausgabe.", "dauer_s": 29.0, "hook": {"gesprochen": f"Satz {i}.", "text": f"Satz {i}"}}
        for i in range(n)
    ]  # fmt: skip
    return {
        "variante": version, "fassung": 1 if version == "v1" else 2, "schalter": {}, "quelle": "q", "quelle_stunden": 0.25,
        "vorschlaege": n + len(reasons), "verworfen": bc.rejection_rates([{"reason": r} for r in reasons], n + len(reasons)),
        "verworfen_gesamt": len(reasons), "modellaufrufe": 2 * n + 3, "modellaufrufe_je_prompt": {}, "laufzeit_s": 0.1,
        "hooks_mit_befund": 1 if version == "v1" else 0, "editorial_v1": {"bestanden": passed, "gruende": [] if passed else ["Segment endet auf verbotenem Out-Point „nicht“"]},
        "angeboten": clips, "clip_candidates": [],
    }  # fmt: skip


def _synthetic_dir(tmp_path):
    """Zwei Quellen, je Version Läufe mit bekannten Zahlen, dazu Bogen und Schlüssel aus ``make_pairs``."""
    runs = {
        "fall_a": {"v1": _synthetic_run("v1", 3, ["gate", "too_long"], False), "v2": _synthetic_run("v2", 2, ["gate"], True),
                   "v2_basis": _synthetic_run("v2", 2, ["gate"], True), "v2_hooks": _synthetic_run("v2", 2, [], True)},
        "fall_b": {"v1": _synthetic_run("v1", 2, [], True), "v2": _synthetic_run("v2", 2, ["overlap"], True),
                   "v2_basis": _synthetic_run("v2", 2, [], True), "v2_hooks": _synthetic_run("v2", 2, [], True)},
    }  # fmt: skip
    sheet, key = bc.make_pairs(runs, seed=3)
    variants = [
        {"name": "v1", "fassung": 1, "gruppe": None, "schalter": {}},
        {"name": "v2", "fassung": 2, "gruppe": None, "schalter": {}},
        {"name": "v2_basis", "fassung": 2, "gruppe": "basis", "schalter": {"hook.native_spoken": False}},
        {"name": "v2_hooks", "fassung": 2, "gruppe": "hooks", "schalter": {"hook.native_spoken": True}},
    ]  # fmt: skip
    run_doc = {"hinweis": "", "provider": "local-heuristic", "k": 3, "brief": {}, "varianten": variants,
               "gebaute_schalter": ["hook.native_spoken"], "quellen": runs}  # fmt: skip
    for kind, doc in (("sheet", sheet), ("key", key), ("run", run_doc), ("rubric", bc.rubric_template())):
        (tmp_path / bc.FILES[kind]).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_evaluation_of_a_filled_rating(tmp_path):
    out = _synthetic_dir(tmp_path)
    sheet, key = _load(out, "sheet"), _load(out, "key")
    for pair in sheet["paare"]:
        mapping = key["paare"][pair["paar_id"]]
        for side in ("A", "B"):
            pair["bewertung"][side] = dict.fromkeys(bc.CRITERIA, 3 if mapping[side] == "v2" else 2)
            pair["bewertung"][side]["natuerlichkeit"] = None
        pair["bewertung"]["praeferenz"] = "A" if mapping["A"] == "v2" else "B"
    sheet["paare"][0]["bewertung"]["praeferenz"] = "gleich"
    (out / bc.FILES["sheet"]).write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")

    res = bc.evaluate(out)
    assert res["paare"] == res["bewertete_paare"] == 4
    assert res["mittel"]["v1"]["quellentreue"] == 2.0 and res["mittel"]["v2"]["quellentreue"] == 3.0
    assert res["mittel"]["v1"]["natuerlichkeit"] is None and res["anzahl"]["v2"]["eigenstaendigkeit"] == 4
    assert res["praeferenz"] == {"v1": 0, "v2": 3, "gleich": 1, "offen": 0}
    assert [(i["quelle"], i["version"], i["rang"]) for i in res["nicht_gepaart"]] == [("fall_a", "v1", 3)]
    v1, v2 = res["varianten"]["v1"], res["varianten"]["v2"]
    assert v1["verworfen"] == {"gate": {"anzahl": 1, "quote": 0.1429}, "too_long": {"anzahl": 1, "quote": 0.1429}}
    assert v2["verworfen"] == {"gate": {"anzahl": 1, "quote": 0.1667}, "overlap": {"anzahl": 1, "quote": 0.1667}}
    assert v1["verwerfungsquote"] == 0.2857 and v2["verwerfungsquote"] == 0.3333
    assert v1["modellaufrufe_je_stunde"] == 32.0 and v2["modellaufrufe_je_stunde"] == 28.0
    assert v1["bestehensquote"] == 0.5 and v2["bestehensquote"] == 1.0

    report = bc.report_markdown(res)
    assert bc.NOTE in report
    assert "\u2013" not in report and "\u2014" not in report and " - " not in report
    for line in (
        "| Quellentreue | 2,00 (n = 4) | 3,00 (n = 4) |",
        "| Natürlichkeit | nicht bewertet (n = 0) | nicht bewertet (n = 0) |",
        "Präferenz: v1 0, v2 3, gleich 1, offen 0.",
        "| gate | 1 (14,3 %) | 1 (16,7 %) |",
        "| too_long | 1 (14,3 %) | 0 |",
        "| gesamt | 2 von 7 (28,6 %) | 2 von 6 (33,3 %) |",
        "| Modellaufrufe je Quellstunde | 32,0 | 28,0 |",
        "* v1: 1 von 2 (50,0 %)",
        "* v2: 2 von 2 (100,0 %)",
        "| Hooks | hook.native_spoken | hook.native_spoken ja | 4 | 0,0 % | 28,0 | 0 | 2 von 2 |",
    ):
        assert line in report, line
    assert "Einzelne Schalter (Auswahl, Hooks, Kürzung, Kombination)" in report


def test_evaluation_rejects_values_outside_the_anchors(tmp_path):
    out = _synthetic_dir(tmp_path)
    sheet = _load(out, "sheet")
    sheet["paare"][0]["bewertung"]["A"]["quellentreue"] = 5
    (out / bc.FILES["sheet"]).write_text(json.dumps(sheet), encoding="utf-8")
    with pytest.raises(SystemExit, match="0 bis 4"):
        bc.evaluate(out)
    sheet["paare"][0]["bewertung"]["A"]["quellentreue"] = None
    sheet["paare"][0]["bewertung"]["praeferenz"] = "v2"
    (out / bc.FILES["sheet"]).write_text(json.dumps(sheet), encoding="utf-8")
    with pytest.raises(SystemExit, match="praeferenz"):
        bc.evaluate(out)


def test_cli_writes_report(generated, tmp_path, capsys):
    for name in ("sheet", "key", "run"):
        (tmp_path / bc.FILES[name]).write_bytes((generated / bc.FILES[name]).read_bytes())
    bc.main(["--auswerten", str(tmp_path)])
    text = (tmp_path / bc.FILES["report"]).read_text(encoding="utf-8")
    assert text.startswith("# Blindvergleich v1 gegen v2")
    assert "Präferenz: v1 0, v2 0, gleich 0, offen" in text
    assert "Bericht geschrieben" in capsys.readouterr().out


# -- Raster, Schalter, Fälle -----------------------------------------------------------------------


def test_rubric_template_has_anchors_0_to_4(generated):
    rubric = _load(generated, "rubric")
    assert list(rubric["kriterien"]) == [
        "quellentreue", "eigenstaendigkeit", "einstieg", "aufbau", "abschluss", "natuerlichkeit", "duplikate", "manuelle_nacharbeit",
    ]  # fmt: skip
    for spec in rubric["kriterien"].values():
        assert list(spec["anker"]) == ["0", "1", "2", "3", "4"]
        assert all(text.strip() for text in spec["anker"].values())
    blob = json.dumps(rubric, ensure_ascii=False)
    assert "–" not in blob and "—" not in blob


def test_switch_variants_are_built_from_policy_overrides():
    variants = {v.name: v for v in bc.switch_variants({"cut.padding": True})}
    assert dict(variants["v2_basis"].overrides) == dict.fromkeys(["gates.discard_hard", "hook.native_spoken", "search.payoff_first", "trim.enabled"], False)
    assert dict(variants["v2_hooks"].overrides)["hook.native_spoken"] is True
    assert dict(variants["v2_hooks"].overrides)["trim.enabled"] is False
    assert all(dict(variants["v2_kombination"].overrides).values())
    assert dict(variants["v2_override"].overrides) == {"cut.padding": True}


def test_policy_variant_applies_and_restores(monkeypatch):
    monkeypatch.setenv(editorial.POLICY_VERSION_ENV, "1")
    monkeypatch.delenv("EDITORIAL_DIR", raising=False)
    variant = bc.Variant("x", 2, (("hook.native_spoken", False), ("trim.enabled", True)))
    with bc.policy_variant(variant) as pol:
        assert pol.version == 2 and editorial.load().version == 2
        assert pol.roh["implementation"]["hook"]["native_spoken"] is False
        assert pol.roh["implementation"]["trim"]["enabled"] is True
        assert pol.hook_native_spoken is False
    assert os.environ[editorial.POLICY_VERSION_ENV] == "1"
    assert "EDITORIAL_DIR" not in os.environ
    assert editorial.load().version == 1


def test_parse_overrides():
    assert bc.parse_overrides(["trim.enabled=true"], "hook.native_spoken=false, ") == {"hook.native_spoken": False, "trim.enabled": True}
    with pytest.raises(SystemExit, match="ungültig"):
        bc.parse_overrides(["trim.enabled=ja"])
    with pytest.raises(SystemExit, match="ungültig"):
        bc.parse_overrides(["laenge.ziel_s=true"])


def test_case_result_for_weak_material():
    case = next(s["case"] for s in bc.fixture_sources() if s["name"] == "fall_weak_material")
    assert case["expected"]["expect_reject"]["value"] is True
    assert bc.case_result(case, [], {}, {}) == {"bestanden": True, "gruende": []}
    offered = [{"candidate_id": "c1", "segments": [], "removed_spans": []}]
    res = bc.case_result(case, offered, {"c1": {}}, {})
    assert res["bestanden"] is False and "Verwerfen erwartet" in res["gruende"][0]
