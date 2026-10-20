"""Referenzdatensatz ``eval/data``: Validierung, Split-Regeln, Gold und Silber, RTTM, Ordnerprüfung."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import data_loader as dl

DATA = Path(__file__).resolve().parents[1] / "eval" / "data"


def _src(**kw):
    base = {"id": "q1", "teil": "entwicklung", "format": "debatte", "sprachvariante": "DE", "dauer_s": 60.0}
    return {**base, **kw}


def test_split_accepts_valid_and_defaults_recording():
    split = dl.validate_split({"quellen": [_src(), _src(id=None, dateiname="b.mp4", teil="abschluss")]})
    assert [dl.source_key(s) for s in split["quellen"]] == ["q1", "b.mp4"]
    assert split["quellen"][0]["aufnahme"] == "q1"
    assert [dl.source_key(s) for s in dl.sources_in(split, "abschluss")] == ["b.mp4"]


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        ([_src(id=None)], "id oder dateiname fehlt"),
        ([_src(), _src()], "steht doppelt"),
        ([_src(teil="test")], "teil 'test' ist nicht erlaubt"),
        ([_src(format="vlog")], "format 'vlog'"),
        ([_src(sprachvariante="FR")], "sprachvariante 'FR'"),
        ([_src(dauer_s=0)], "dauer_s muss eine positive Zahl"),
        ([_src(aufnahme="r"), _src(id="q2", aufnahme="r", teil="abschluss")], "Ausschnitte derselben Aufnahme"),
    ],
)
def test_split_errors_are_clear(sources, message):
    with pytest.raises(dl.DataError, match=message):
        dl.validate_split({"quellen": sources})


def test_sources_in_rejects_unknown_part():
    with pytest.raises(dl.DataError, match="Teil 'x'"):
        dl.sources_in({"quellen": []}, "x")


def test_abschluss_is_locked_without_confirmation():
    with pytest.raises(dl.DataError, match="abschluss ist gesperrt"):
        dl.check_part_access("abschluss", False)
    dl.check_part_access("abschluss", True)
    dl.check_part_access("entwicklung", False)


def test_spans_validation():
    doc = dl.validate_spans({"spannen": [{"person": "a", "start_s": 1, "end_s": 5, "platform": "tiktok"}]})
    assert doc["spannen"][0] == {"person": "a", "start_s": 1.0, "end_s": 5.0, "platform": "tiktok", "views": None}
    with pytest.raises(dl.DataError, match="Ende muss nach dem Anfang"):
        dl.validate_spans({"spannen": [{"person": "a", "start_s": 5, "end_s": 1, "platform": "tiktok"}]})
    with pytest.raises(dl.DataError, match="views"):
        dl.validate_spans({"spannen": [{"person": "a", "start_s": 1, "end_s": 5, "platform": "tiktok", "views": -1}]})
    with pytest.raises(dl.DataError, match="platform"):
        dl.validate_spans({"spannen": [{"person": "a", "start_s": 1, "end_s": 5, "platform": "x"}]})
    with pytest.raises(dl.DataError, match="person fehlt"):
        dl.validate_spans({"spannen": [{"start_s": 1, "end_s": 5, "platform": "tiktok"}]})


def test_span_iou():
    assert dl.span_iou({"start_s": 0, "end_s": 10}, {"start_s": 5, "end_s": 15}) == 1 / 3
    assert dl.span_iou({"start_s": 0, "end_s": 1}, {"start_s": 2, "end_s": 3}) == 0.0


def test_gold_silver():
    spans = [
        {"person": "a", "start_s": 10, "end_s": 40},
        {"person": "b", "start_s": 12, "end_s": 42},
        {"person": "a", "start_s": 11, "end_s": 41},  # dieselbe Person zählt nicht doppelt
        {"person": "c", "start_s": 100, "end_s": 130},
        {"person": "c", "start_s": 101, "end_s": 129},  # zweimal dieselbe Person: zwei Silber
    ]
    moments = dl.gold_silver(spans)
    gold = [m for m in moments if m["stufe"] == "gold"]
    assert len(gold) == 1 and gold[0]["personen"] == ["a", "b"] and gold[0]["spannen"] == 3
    assert gold[0]["start_s"] == 11.0 and gold[0]["end_s"] == 41.0
    assert [m["stufe"] for m in moments if m["start_s"] >= 100] == ["silber", "silber"]
    assert dl.gold_silver([]) == []


def test_editors_validation():
    doc = dl.validate_editors({"redakteure": [{"person": "r", "top10": [{"rang": 2, "start_s": 0, "end_s": 5}, {"rang": 1, "start_s": 9, "end_s": 20}]}]})
    assert [x["rang"] for x in doc["redakteure"][0]["top10"]] == [1, 2]
    with pytest.raises(dl.DataError, match="rang 1 ist doppelt"):
        dl.validate_editors({"redakteure": [{"person": "r", "top10": [{"rang": 1, "start_s": 0, "end_s": 5}] * 2}]})
    with pytest.raises(dl.DataError, match="höchstens 10"):
        dl.validate_editors({"redakteure": [{"person": "r", "top10": [{"rang": i % 10 + 1, "start_s": 0, "end_s": 5} for i in range(11)]}]})
    with pytest.raises(dl.DataError, match="rang 11"):
        dl.validate_editors({"redakteure": [{"person": "r", "top10": [{"rang": 11, "start_s": 0, "end_s": 5}]}]})
    with pytest.raises(dl.DataError, match="steht doppelt"):
        dl.validate_editors({"redakteure": [{"person": "r", "top10": [{"rang": 1, "start_s": 0, "end_s": 5}]}] * 2})


def test_parse_rttm():
    segs = dl.parse_rttm("# Kommentar\nSPEAKER f 1 0.5 2.0 <NA> <NA> s1 <NA> <NA>\n\n")
    assert segs == [{"sprecher": "s1", "start": 0.5, "end": 2.5}]
    with pytest.raises(dl.DataError, match="Zeile 1"):
        dl.parse_rttm("LEXEME f 1 0 1")
    with pytest.raises(dl.DataError, match="Dauer"):
        dl.parse_rttm("SPEAKER f 1 0 0 <NA> <NA> s1")


def test_transcript_reference_and_rttm_file(tmp_path):
    doc = dl.validate_transcript_reference({"woerter": [{"wort": "ja", "start": 0, "end": 0.3, "sprecher": "A"}]})
    assert doc["sprachvariante"] == "DE" and doc["segmente"] == []
    with pytest.raises(dl.DataError, match="sprecher fehlt"):
        dl.validate_transcript_reference({"woerter": [{"wort": "ja", "start": 0, "end": 0.3}]})
    with pytest.raises(dl.DataError, match="sprachvariante"):
        dl.validate_transcript_reference({"woerter": [], "sprachvariante": "XX"})
    rttm = tmp_path / "q.rttm"
    rttm.write_text("SPEAKER q 1 0 1 <NA> <NA> a <NA> <NA>\n", encoding="utf-8")
    assert dl.load_transcript_reference(rttm)["segmente"][0]["sprecher"] == "a"
    with pytest.raises(dl.DataError, match="Datei fehlt"):
        dl.load_transcript_reference(tmp_path / "fehlt.rttm")


def test_anchors_and_cut_points():
    a = dl.validate_anchors({"anker": [{"wort": "Wien", "anker_start": 1, "anker_ende": 1.3, "kategorie": "name"}]})
    assert a["anker"][0]["kategorie"] == "name"
    with pytest.raises(dl.DataError, match="kategorie"):
        dl.validate_anchors({"anker": [{"wort": "x", "anker_start": 1, "anker_ende": 2, "kategorie": "zahl"}]})
    c = dl.validate_cut_points({"schnittpunkte": [{"clip_id": "c", "zeit_s": 1, "urteil": "abgehackt", "hoerer": "h"}],
                                "clip_urteile": [{"clip_id": "c", "hoerer": "h", "urteil": "unbrauchbar"}]})  # fmt: skip
    assert c["clip_urteile"][0]["urteil"] == "unbrauchbar"
    with pytest.raises(dl.DataError, match="urteil"):
        dl.validate_cut_points({"schnittpunkte": [{"clip_id": "c", "zeit_s": 1, "urteil": "gut", "hoerer": "h"}]})
    with pytest.raises(dl.DataError, match="zeit_s"):
        dl.validate_cut_points({"schnittpunkte": [{"clip_id": "c", "zeit_s": -1, "urteil": "natuerlich", "hoerer": "h"}]})


def test_load_errors_name_the_file(tmp_path):
    bad = tmp_path / "split.json"
    bad.write_text("{nicht json", encoding="utf-8")
    with pytest.raises(dl.DataError, match="kein gültiges JSON"):
        dl.load_split(bad)
    with pytest.raises(dl.DataError, match="Datei fehlt"):
        dl.load_spans(tmp_path / "x.json")
    with pytest.raises(dl.DataError, match="Liste fehlt"):
        dl.validate_spans({})


def test_example_folder_is_valid_and_complete():
    res = dl.validate_folder(DATA / "beispiel")
    assert res["je_teil"] == {"entwicklung": 2, "kalibrierung": 1, "abschluss": 1}
    assert res["dateien_geprueft"] == 6 and res["ohne_split_eintrag"] == []
    data = dl.load_source_data(DATA / "beispiel", "beispiel_debatte")
    assert data["fehlt"] == [] and len(data["spannen"]["spannen"]) == 6
    podcast = dl.load_source_data(DATA / "beispiel", "beispiel_podcast")
    assert podcast["transkript_referenz"]["woerter"] == [] and "spannen" in podcast["fehlt"]
    assert dl.load_editors(DATA / "beispiel" / "redakteure" / "beispiel_debatte.json")["redakteure"][0]["person"] == "red_1"
    assert dl.load_anchors(DATA / "beispiel" / "audioanker" / "beispiel_debatte.json")["anker"]
    assert dl.load_cut_points(DATA / "beispiel" / "schnittpunkte" / "beispiel_debatte.json")["schnittpunkte"]


def test_real_split_holds_existing_material_in_development():
    split = dl.load_split(DATA / "split.json")
    keys = {dl.source_key(s) for s in split["quellen"]}
    assert sum(1 for k in keys if k.startswith("fall_")) == 14
    assert {"quelle_16982bb5-f2e4-4d89-81ed-1ca44fd391d7", "quelle_c958814e-6c21-41ee-bcc5-ea2c5cf3795b"} <= keys
    assert {"a_interview_handwerk", "b_monolog_gruenderin", "c_debatte_viertagewoche"} <= keys
    assert {s["teil"] for s in split["quellen"]} == {"entwicklung"}
    assert dl.sources_in(split, "abschluss") == [] and split["abschluss_hinweis"]


def test_folder_reports_files_without_split_entry(tmp_path, capsys):
    (tmp_path / "split.json").write_text(json.dumps({"quellen": [_src()]}), encoding="utf-8")
    (tmp_path / "spannen").mkdir()
    (tmp_path / "spannen" / "fremd.json").write_text(json.dumps({"spannen": []}), encoding="utf-8")
    assert dl.validate_folder(tmp_path)["ohne_split_eintrag"] == ["spannen/fremd.json"]
    dl.main([str(tmp_path)])
    assert "Warnung: spannen/fremd.json" in capsys.readouterr().out
    (tmp_path / "spannen" / "fremd.json").write_text(json.dumps({"spannen": [{"person": "a"}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="Fehler: .*fremd.json"):
        dl.main([str(tmp_path)])
