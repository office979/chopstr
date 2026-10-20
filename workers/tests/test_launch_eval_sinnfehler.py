"""Sinnfehler-Bogen: Clopper-Pearson gegen die Review-Zahlen, Auswertung, Validierung, CLI."""

from __future__ import annotations

import json

import pytest

from eval import sinnfehler as sf


def test_clopper_pearson_matches_review_numbers():
    assert round(sf.clopper_pearson_upper(0, 20), 3) == 0.139
    assert round(sf.clopper_pearson_upper(1, 20), 3) == 0.216
    assert sf.clopper_pearson_upper(0, 0) is None and sf.clopper_pearson_upper(3, 3) == 1.0
    assert sf.binom_cdf(0, 20, sf.clopper_pearson_upper(0, 20)) == pytest.approx(0.05, abs=1e-9)


def _sheet(n=20, sources=3, errors=()):
    clips = [{"clip_id": f"c{i}", "quelle": f"q{i % sources}", "text": "", "geprueft": True, "kritische_sinnfehler": []} for i in range(n)]
    for idx, cat, confirmed in errors:
        clips[idx]["kritische_sinnfehler"].append({"kategorie": cat, "bestaetigt": confirmed, "beschreibung": "x"})
    return {"bogen": sf.SHEET, "clips": clips}


def test_evaluate_counts_confirmed_errors_and_sources():
    res = sf.evaluate(_sheet(errors=[(0, "negation", True), (0, "number", True), (3, "condition", False)]))
    assert res["stichprobe"] == 20 and res["mit_bestaetigtem_fehler"] == 1 and res["beobachtet_anteil"] == 0.05
    assert round(res["obere_grenze_95"], 3) == 0.216 and res["unbestaetigte_hinweise"] == 1
    assert res["je_kategorie"]["negation"] == 1 and res["je_kategorie"]["condition"] == 0
    assert res["je_quelle"]["q0"] == {"geprueft": 7, "mit_fehler": 1} and res["gesperrte_clips"] == ["c0"]
    assert res["warnungen"] == [] and res["metriken"]["sinnfehler_obere_grenze"]["stichprobe"] == 20
    text = sf.format_report(res)
    assert "1 von 20" in text and "21,6 %" in text and "Gesperrt" in text


def test_small_sample_warns_and_unchecked_clips_do_not_count():
    sheet = _sheet(n=5, sources=1)
    sheet["clips"][4]["geprueft"] = False
    res = sf.evaluate(sheet)
    assert res["stichprobe"] == 4 and len(res["warnungen"]) == 2
    nothing = sf.evaluate({"clips": [{"clip_id": "a", "quelle": "q", "geprueft": False}]})
    assert nothing["obere_grenze_95"] is None and nothing["metriken"]["sinnfehler_beobachtet"]["ursache"] == "kein geprüfter Clip"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c.update(geprueft="ja"), "geprueft muss true oder false"),
        (lambda c: c["kritische_sinnfehler"].append({"kategorie": "stil", "bestaetigt": True}), "kategorie muss"),
        (lambda c: c["kritische_sinnfehler"].append({"kategorie": "time", "bestaetigt": "ja"}), "bestaetigt muss"),
        (lambda c: c.update(geprueft=False, kritische_sinnfehler=[{"kategorie": "time", "bestaetigt": True}]), "geprueft ist false"),
        (lambda c: c.pop("quelle"), "clip_id und quelle"),
    ],
)
def test_validation_errors(mutate, message):
    sheet = _sheet(n=2)
    mutate(sheet["clips"][0])
    with pytest.raises(SystemExit, match=message):
        sf.evaluate(sheet)
    with pytest.raises(SystemExit, match="doppelt"):
        sf.validate_sheet({"clips": [{"clip_id": "a", "quelle": "q", "geprueft": True}] * 2})
    with pytest.raises(SystemExit, match="clips fehlt"):
        sf.validate_sheet({})


def test_make_sheet_and_cli(tmp_path, capsys):
    clips = tmp_path / "clips.json"
    clips.write_text(json.dumps([{"clip_id": 1, "quelle": "q", "text": "Satz."}]), encoding="utf-8")
    sheet = tmp_path / "bogen.json"
    sf.main(["--bogen-aus", str(clips), "--out", str(sheet), "--pruefer", "p1"])
    doc = json.loads(sheet.read_text(encoding="utf-8"))
    assert doc["pruefer"] == "p1" and doc["clips"][0] == {"clip_id": "1", "quelle": "q", "text": "Satz.", "geprueft": False, "kritische_sinnfehler": []}
    doc["clips"][0]["geprueft"] = True
    sheet.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "e.json"
    sf.main(["--auswerten", str(sheet), "--json", str(out)])
    assert "0 von 1" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["obere_grenze_95"] == pytest.approx(0.95)
    with pytest.raises(SystemExit, match="--out"):
        sf.main(["--bogen-aus", str(clips)])
