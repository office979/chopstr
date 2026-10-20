"""Highlight-Versatz gegen Audioanker: Zuordnung, Median, 95. Perzentil, fehlende Alignments, Kategorien."""

from __future__ import annotations

import json

import pytest

from eval import alignment_eval as ae


def a(word, start, end, cat="sonstiges"):
    return {"wort": word, "anker_start": start, "anker_ende": end, "kategorie": cat}


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_percentile_and_median():
    assert ae.percentile([], 95) is None and ae.median([]) is None
    assert ae.percentile(list(range(1, 21)), 95) == 19 and ae.percentile([5.0], 95) == 5.0
    assert ae.median([1, 3, 2]) == 2 and ae.median([1, 2, 3, 4]) == 2.5


def test_match_anchors_nearest_word_and_missing():
    words = [w("Wien", 1.0, 1.4), w("Wien", 10.02, 10.41), w("nicht", 5.0, None), w("zwölf", 7.0, 7.3)]
    rows = ae.match_anchors([a("Wien", 10.0, 10.4, "name"), a("nicht", 5.0, 5.3), a("Bern", 3.0, 3.3), a("zwölf", 20.0, 20.3)], words)
    assert rows[0]["status"] == "ok" and rows[0]["wort_index"] == 1
    assert rows[0]["versatz_anfang_ms"] == pytest.approx(20.0) and rows[0]["versatz_ende_ms"] == pytest.approx(10.0)
    assert rows[1]["status"] == "ok" and "versatz_ende_ms" not in rows[1]  # Ende ohne Zeit
    assert rows[2]["status"] == "nicht_gefunden" and rows[3]["status"] == "nicht_gefunden"  # außerhalb des Fensters
    timeless = ae.match_anchors([a("ja", 1.0, 1.2)], [w("ja", None, None)])
    assert timeless[0]["status"] == "ohne_zeit"
    # jedes Wort nur einmal
    twice = ae.match_anchors([a("ja", 1.0, 1.2), a("ja", 1.05, 1.25)], [w("ja", 1.0, 1.2)])
    assert [x["status"] for x in twice] == ["ok", "nicht_gefunden"]


def test_evaluate_per_category_and_metrics():
    anchors = [a("Wien", 1.0, 1.4, "name"), a("nicht", 2.0, 2.3, "verneinung"), a("fehlt", 9.0, 9.3, "verneinung")]
    words = [w("Wien", 1.05, 1.38), w("nicht", 1.9, 2.4)]
    res = ae.evaluate(anchors, words)
    g = res["gesamt"]
    assert g["fehlend"] == 1 and g["fehlend_anteil"] == pytest.approx(1 / 3) and g["fehlend_je_grund"]["nicht_gefunden"] == 1
    assert g["anfang"]["median_ms"] == pytest.approx(75.0) and g["anfang"]["median_mit_vorzeichen_ms"] == pytest.approx(-25.0)
    assert res["je_kategorie"]["name"]["anfang"]["median_ms"] == pytest.approx(50.0)
    assert res["je_kategorie"]["verneinung"]["fehlend"] == 1
    m = res["metriken"]
    assert m["versatz_ende_p95_ms"]["wert"] == pytest.approx(100.0) and m["alignment_fehlend_anteil"]["stichprobe"] == 3
    empty = ae.evaluate([], words)
    assert empty["metriken"]["versatz_anfang_median_ms"] == {"wert": None, "stichprobe": 0, "ursache": "keine Anker"}
    assert empty["metriken"]["alignment_fehlend_anteil"]["wert"] is None
    lost = ae.evaluate([a("x", 1, 2)], [])
    assert lost["metriken"]["versatz_anfang_median_ms"]["ursache"] == "kein Wort mit Zeit gefunden"
    assert "nicht messbar: kein Wort mit Zeit gefunden" in ae.format_report(lost)


def test_anchors_from_speaker_changes():
    doc = {"saetze": [{"text": "Hallo du.", "start": 1.0, "end": 2.0}, {"text": "Ja.", "start": 3.0, "end": 3.5}, {"text": "...", "start": 4, "end": 5}]}
    anchors = ae.anchors_from_speaker_changes(doc)
    assert anchors == [
        {"wort": "Hallo", "anker_start": 1.0, "anker_ende": None, "kategorie": "sonstiges"},
        {"wort": "du.", "anker_start": None, "anker_ende": 2.0, "kategorie": "sonstiges"},
        {"wort": "Ja.", "anker_start": 3.0, "anker_ende": 3.5, "kategorie": "sonstiges"},
    ]
    rows = ae.match_anchors(anchors, [w("hallo", 0.8, 1.2), w("du", 1.2, 1.9), w("ja", 3.0, 3.5)])
    assert rows[0]["versatz_anfang_ms"] == pytest.approx(-200.0) and "versatz_ende_ms" not in rows[0]
    assert rows[1]["versatz_ende_ms"] == pytest.approx(-100.0) and "versatz_anfang_ms" not in rows[1]


def test_cli(tmp_path, capsys):
    (tmp_path / "anker.json").write_text(json.dumps({"anker": [a("Wien", 1.0, 1.4, "name")]}), encoding="utf-8")
    (tmp_path / "t.json").write_text(json.dumps({"words": [w("Wien", 1.01, 1.4)]}), encoding="utf-8")
    out = tmp_path / "v.json"
    ae.main(["--anker", str(tmp_path / "anker.json"), "--transkript", str(tmp_path / "t.json"), "--json", str(out)])
    assert "name: 1 Anker" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["versatz_anfang_median_ms"]["wert"] == pytest.approx(10.0)
    (tmp_path / "bad.json").write_text(json.dumps({"anker": [a("x", 1, 2, "zahl")]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="kategorie"):
        ae.main(["--anker", str(tmp_path / "bad.json"), "--transkript", str(tmp_path / "t.json")])
