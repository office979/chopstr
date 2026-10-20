"""Sprecherzuordnung je Wort, cpWER und DER (eigene Implementierung) mit bekannten Ergebnissen."""

from __future__ import annotations

import json

import pytest

from eval import speaker_eval as se


def w(text, start, end, spk):
    return {"text": text, "start": start, "end": end, "speaker": spk}


def r(text, start, end, spk):
    return {"wort": text, "start": start, "end": end, "sprecher": spk}


def test_best_mapping_exact_and_greedy():
    weights = {("h1", "r2"): 5.0, ("h2", "r1"): 3.0, ("h1", "r1"): 4.0}
    assert se.best_mapping(weights, ["h1", "h2"], ["r1", "r2"]) == {"h1": "r2", "h2": "r1"}
    # exakt: h1 nach r1 (6) wäre gierig, h1 nach r2 und h2 nach r1 ergibt 5 + 4 = 9
    assert se.best_mapping({("h1", "r1"): 6.0, ("h1", "r2"): 5.0, ("h2", "r1"): 4.0}, ["h1", "h2"], ["r1", "r2"]) == {"h1": "r2", "h2": "r1"}
    refs = [f"r{i:02d}" for i in range(13)]
    greedy = se.best_mapping({("h", "r05"): 2.0, ("h", "r06"): 1.0}, ["h"], refs)
    assert greedy == {"h": "r05"}
    assert se.best_mapping({}, ["h"], ["r"]) == {}


def test_align_words_maps_reference_to_hypothesis():
    ref = [r("a", 0, 1, "A"), r("b", 1, 2, "A"), r("c", 2, 3, "A")]
    hyp = [w("a", 0, 1, "X"), w("x", 1, 2, "X"), w("c", 2, 3, "X"), w("d", 3, 4, "X")]
    assert se.align_words(ref, hyp) == {0: 0, 1: 1, 2: 2}
    assert se.align_words(ref, []) == {}


def test_segments_from_words_and_overlap_regions():
    words = [w("a", 0, 1, "A"), w("b", 1.5, 2, "A"), w("c", 4, 5, "A"), w("d", 5, 6, None), w("e", 4.5, 6, "B")]
    segs = se.segments_from_words(words)
    assert segs == [{"sprecher": "A", "start": 0, "end": 2}, {"sprecher": "A", "start": 4, "end": 5}, {"sprecher": "B", "start": 4.5, "end": 6}]
    assert se.overlap_regions(segs) == [(4.5, 5)]
    assert se.overlap_regions([]) == []


def test_speaker_attribution_counts_each_category():
    ref = [r("hallo", 0, 1, "A"), r("welt", 1, 2, "A"), r("ja", 1.5, 2.5, "B"), r("genau", 2.5, 3, "B"), r("weg", 3, 4, "B")]
    ref_segs = [{"sprecher": "A", "start": 0, "end": 2}, {"sprecher": "B", "start": 1.5, "end": 4}]
    hyp = [w("hallo", 0, 1, "S1"), w("welt", 1, 2, "S1"), w("ja", 1.5, 2.5, "S1"), w("genau", 2.5, 3, None)]
    res = se.speaker_attribution(ref, hyp, ref_segs)
    g = res["gesamt"]
    assert (g["korrekt"], g["falsch"], g["nicht_zugeordnet"], g["nicht_erkannt"]) == (2, 1, 1, 1)
    assert g["korrekt_anteil"] == 0.4 and res["zuordnung"] == {"S1": "A"}
    ov = res["overlap"]
    assert ov["woerter"] == 2 and ov["korrekt"] == 1 and ov["falsch"] == 1
    no_overlap = se.speaker_attribution(ref[:2], hyp[:2], [{"sprecher": "A", "start": 0, "end": 2}])
    assert no_overlap["overlap"] is None and no_overlap["overlap_ursache"] == "keine Überlappung in der Referenz"
    assert se.speaker_attribution([], hyp)["ursache"] == "Referenz ohne Wörter"


def test_cpwer_known_values():
    ref = [r("eins", 0, 1, "A"), r("zwei", 1, 2, "A"), r("drei", 2, 3, "A"), r("vier", 3, 4, "B"), r("fünf", 4, 5, "B")]
    hyp = [w("eins", 0, 1, "Y"), w("zwei", 1, 2, "Y"), w("drei", 2, 3, "Y"), w("vier", 3, 4, "X"), w("sechs", 4, 5, "X")]
    res = se.cpwer(ref, hyp)
    assert res["cpwer"] == pytest.approx(1 / 5) and res["zuordnung"] == {"X": "B", "Y": "A"}
    merged = [{**x, "speaker": "Z"} for x in hyp[:3]] + [w("vier", 3, 4, "Z"), w("fünf", 4, 5, "Z")]
    assert se.cpwer(ref, merged)["cpwer"] == pytest.approx(4 / 5)
    assert se.cpwer([], hyp)["cpwer"] is None


def test_der_missed_false_alarm_confusion():
    ref = [{"sprecher": "A", "start": 0, "end": 10}, {"sprecher": "B", "start": 5, "end": 10}]
    perfect = se.der(ref, [{"sprecher": "x", "start": 0, "end": 10}, {"sprecher": "y", "start": 5, "end": 10}])
    assert perfect["der"] == 0.0
    res = se.der(ref, [{"sprecher": "x", "start": 0, "end": 10}, {"sprecher": "y", "start": 20, "end": 25}])
    assert res["referenz_s"] == 15 and res["missed_s"] == 5 and res["false_alarm_s"] == 5 and res["confusion_s"] == 0
    assert res["der"] == pytest.approx(10 / 15)
    conf = se.der([{"sprecher": "A", "start": 0, "end": 10}, {"sprecher": "B", "start": 10, "end": 20}], [{"sprecher": "x", "start": 0, "end": 20}])
    assert conf["confusion_s"] == 10 and conf["der"] == 0.5
    assert se.der([], [{"sprecher": "x", "start": 0, "end": 1}])["der"] is None


def test_reference_from_speaker_changes():
    doc = {"turns": [{"sprecher": "S0", "start": 0.0, "end": 2.0}],
           "saetze": [{"sprecher": "S0", "text": "Ab cd.", "start": 0.0, "end": 2.0}]}  # fmt: skip
    ref = se.reference_from_speaker_changes(doc)
    assert [x["wort"] for x in ref["woerter"]] == ["Ab", "cd."]
    assert ref["woerter"][0]["end"] == pytest.approx(0.8) and ref["woerter"][1]["end"] == pytest.approx(2.0)
    assert ref["segmente"] == [{"sprecher": "S0", "start": 0.0, "end": 2.0}]


def test_loaders_and_evaluate(tmp_path):
    doc = {"turns": [{"sprecher": "S0", "start": 0.0, "end": 1.0}, {"sprecher": "S1", "start": 1.5, "end": 2.5}],
           "saetze": [{"sprecher": "S0", "text": "guten Tag", "start": 0.0, "end": 1.0}, {"sprecher": "S1", "text": "hallo", "start": 1.5, "end": 2.5}]}  # fmt: skip
    (tmp_path / "sprecherwechsel.json").write_text(json.dumps(doc), encoding="utf-8")
    words = [w("guten", 0.0, 0.5, "B"), w("Tag", 0.5, 1.0, "B"), w("hallo", 1.5, 2.5, "A")]
    (tmp_path / "hyp.json").write_text(json.dumps({"words": words}), encoding="utf-8")
    (tmp_path / "ref.rttm").write_text("SPEAKER x 1 0 1 <NA> <NA> S0 <NA> <NA>\n", encoding="utf-8")
    (tmp_path / "hyp.rttm").write_text("SPEAKER x 1 0 1 <NA> <NA> B <NA> <NA>\n", encoding="utf-8")
    ref = se.load_reference(tmp_path / "sprecherwechsel.json")
    hyp = se.load_hypothesis(tmp_path / "hyp.json")
    res = se.evaluate(ref, hyp)
    assert res["zuordnung_je_wort"]["gesamt"]["korrekt_anteil"] == 1.0 and res["cpwer"]["cpwer"] == 0.0 and res["der"]["der"] == 0.0
    m = res["metriken"]
    assert m["sprecher_korrekt_gesamt"]["wert"] == 1.0 and m["sprecher_korrekt_overlap"]["wert"] is None
    assert m["sprecher_korrekt_overlap"]["ursache"] == "keine Überlappung in der Referenz"
    only_der = se.evaluate(se.load_reference(tmp_path / "ref.rttm"), se.load_hypothesis(tmp_path / "hyp.rttm"))
    assert only_der["der"]["der"] == 0.0
    assert only_der["metriken"]["cpwer"] == {"wert": None, "stichprobe": 0, "ursache": "Referenz ohne Wörter"}
    assert only_der["metriken"]["sprecher_korrekt_gesamt"]["ursache"] == "Referenz ohne Wörter"
    no_hyp_words = se.evaluate(ref, {"woerter": [], "segmente": []})
    assert no_hyp_words["metriken"]["der"]["ursache"] == "Hypothese ohne Sprechersegmente"
    assert "nicht messbar: Hypothese ohne Wörter" in se.format_report(no_hyp_words)


def test_cli_writes_json(tmp_path, capsys):
    ref = {"woerter": [r("ja", 0, 1, "A"), r("nein", 0.5, 1.5, "B")]}
    (tmp_path / "ref.json").write_text(json.dumps(ref), encoding="utf-8")
    (tmp_path / "hyp.json").write_text(json.dumps([w("ja", 0, 1, "1"), w("nein", 0.5, 1.5, "2")]), encoding="utf-8")
    out = tmp_path / "s.json"
    se.main(["--referenz", str(tmp_path / "ref.json"), "--hypothese", str(tmp_path / "hyp.json"), "--json", str(out)])
    text = capsys.readouterr().out
    assert "in Überlappung (2 Wörter): korrekt 100,0 %" in text and "DER (ohne Collar, mit Überlappung): 0,0 %" in text
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["sprecher_korrekt_overlap"]["wert"] == 1.0
    (tmp_path / "bad.json").write_text(json.dumps({"woerter": [{"wort": "x"}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="Fehler: .*bad.json"):
        se.main(["--referenz", str(tmp_path / "bad.json"), "--hypothese", str(tmp_path / "hyp.json")])
