"""Eval-Harness, neuer Teil: Funnel, Abdeckung an drei Stellen, Recall@20, Precision je Redakteur, Grenzfehler
getrennt, neue Momente, Schnittqualität, leere Eingaben als None."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import eval_harness as eh

DATA = Path(__file__).resolve().parents[1] / "eval" / "data"


def s(a, b, **kw):
    return {"start_s": float(a), "end_s": float(b), **kw}


GOLD = {"stufe": "gold", "personen": ["a", "b"]}
SILVER = {"stufe": "silber", "personen": ["c"]}
MOMENTS = [s(10, 40, **GOLD), s(100, 130, **SILVER), s(300, 330, **GOLD)]


def test_old_evaluate_keeps_api_and_splits_boundaries():
    gold = {"clips": [{"start": 10, "end": 40, "rating": 3}]}
    r = eh.evaluate(gold, {"clips": [{"start": 12, "end": 41, "total": 9}]}, k=10)
    assert r["boundary_err_s"] == 1.5 and r["boundary_start_s"] == 2 and r["boundary_end_s"] == 1
    assert r["boundary_weighted_s"] == pytest.approx(5 / 3)


def test_old_evaluate_empty_inputs_are_none():
    r = eh.evaluate({"clips": []}, {"clips": []}, k=10)
    assert r["precision_at_k"] is None and r["recall"] is None and r["boundary_err_s"] is None
    agg = eh.aggregate([r])
    assert agg["precision_at_k"] is None and agg["recall"] is None and agg["n"] == 1
    assert "n. m." in eh.format_table({"DE": agg}, 10)


def test_funnel_stages_from_funnel():
    report = {"funnel": {"pool": [s(0, 10)], "after_gates": [s(0, 10)], "offered": [s(5, 9, rank=2), s(0, 10, rank=1)]}}
    st = eh.funnel_stages(report)
    assert st["offered"]["spannen"][0] == {"start_s": 0.0, "end_s": 10.0} and st["offered"]["herkunft"] == "funnel.offered"
    assert eh.funnel_stages({"funnel": {"pool": []}})["after_gates"]["ursache"] == "funnel.after_gates fehlt im Bericht"


def test_funnel_stages_fallbacks():
    report = {"search": {"chapters": [{"proposals": [s(1, 5)]}, {"proposals": [{"first_sent": 1}]}]},
              "candidates": [s(0, 5, total=1.0), s(10, 20, total=9.0)]}  # fmt: skip
    st = eh.funnel_stages(report)
    assert st["pool"]["spannen"] == [s(1, 5)] and st["pool"]["herkunft"] == "search.chapters.proposals"
    assert st["after_gates"]["spannen"] is None and "nach Gates" in st["after_gates"]["ursache"]
    assert st["offered"]["spannen"][0] == s(10, 20)
    bare = eh.funnel_stages({"search": {"chapters": [{"search": 3}]}})
    assert bare["pool"]["spannen"] is None and "keine Vorschläge mit Zeiten" in bare["pool"]["ursache"]
    assert bare["offered"]["ursache"] == "candidates fehlt im Bericht"
    assert "keine Suchkapitel" in eh.funnel_stages({})["pool"]["ursache"]


def test_coverage_and_none_cases():
    c = eh.coverage(MOMENTS, [s(11, 41), s(500, 530)])
    assert (c["abgedeckt"], c["gesamt"], c["wert"]) == (1, 3, 1 / 3)
    assert eh.coverage(None, [s(0, 1)])["wert"] is None
    assert eh.coverage([], [s(0, 1)])["ursache"] == "keine Referenzmomente"
    assert eh.coverage(MOMENTS, None)["wert"] is None
    assert eh.coverage(MOMENTS, [])["wert"] == 0.0


def test_coverage_funnel_separates_stages_and_gold():
    stages = eh.funnel_stages({"funnel": {"pool": [s(10, 40), s(100, 130), s(300, 330)], "after_gates": [s(10, 40)], "offered": []}})
    cov = eh.coverage_funnel(MOMENTS, stages)
    assert cov["pool"]["alle"]["wert"] == 1.0 and cov["after_gates"]["alle"]["wert"] == 1 / 3
    assert cov["after_gates"]["gold"]["wert"] == 0.5 and cov["offered"]["alle"]["wert"] == 0.0
    missing = eh.coverage_funnel(MOMENTS, eh.funnel_stages({"candidates": []}))
    assert missing["after_gates"]["alle"]["ursache"].startswith("funnel fehlt")


def test_recall_at_uses_first_k():
    offered = [s(500 + i, 510 + i) for i in range(20)] + [s(10, 40)]
    assert eh.recall_at(offered, MOMENTS, k=20)["wert"] == 0.0
    assert eh.recall_at(offered, MOMENTS, k=21)["wert"] == 1 / 3
    assert eh.recall_at(None, MOMENTS)["wert"] is None


def test_precision_at_and_per_editor():
    offered = [s(10, 40), s(500, 530), s(100, 130)]
    p = eh.precision_at(offered, MOMENTS, 5)
    assert (p["treffer"], p["n"], p["wert"]) == (2, 3, 2 / 3)
    assert eh.precision_at([], MOMENTS, 5)["ursache"] == "nichts angeboten"
    assert eh.precision_at(None, MOMENTS, 5)["wert"] is None
    assert eh.precision_at(offered, None, 5)["ursache"] == "keine Referenz"
    editors = [{"person": "r1", "top10": [s(10, 40)]}, {"person": "r2", "top10": [s(100, 130), s(500, 530)]}]
    res = eh.precision_per_editor(offered, editors, ks=(1, 5))
    assert res["je_redakteur"]["r1"]["p@1"]["wert"] == 1.0 and res["je_redakteur"]["r2"]["p@1"]["wert"] == 0.0
    assert res["gemittelt"]["p@5"]["wert"] == pytest.approx((1 / 3 + 2 / 3) / 2)
    empty = eh.precision_per_editor(offered, None)
    assert empty["gemittelt"]["p@5"] == {"wert": None, "ursache": "keine Redakteurs-Top-10"}
    none_offered = eh.precision_per_editor([], editors)
    assert none_offered["gemittelt"]["p@10"]["wert"] is None and none_offered["gemittelt"]["p@10"]["ursache"] == "nichts angeboten"


def test_boundary_errors_start_counts_double():
    b = eh.boundary_errors([s(12, 40), s(100, 136)], MOMENTS)
    assert b["start_s"] == 1.0 and b["ende_s"] == 3.0 and b["n"] == 2
    assert b["gewichtet_s"] == pytest.approx((2 * 1.0 + 3.0) / 3)
    assert eh.boundary_errors([s(900, 930)], MOMENTS)["ursache"] == "kein Treffer mit IoU >= 0,5"
    assert eh.boundary_errors([], MOMENTS)["ursache"] == "keine angebotenen Kandidaten"
    assert eh.boundary_errors([s(1, 2)], None)["ursache"] == "keine Referenz"


def test_new_moments_are_counted_not_failed():
    editors = [{"person": "r", "top10": [s(700, 730)]}]
    n = eh.new_moments([s(10, 40), s(700, 731), s(900, 930)], MOMENTS, editors)
    assert n["anzahl"] == 1 and n["spannen"] == [s(900, 930)]
    assert eh.new_moments(None, MOMENTS, None)["anzahl"] is None
    assert eh.new_moments([s(1, 2)], None, None)["ursache"] == "keine Referenz"


def test_evaluate_source_and_aggregate():
    report = {"funnel": {"pool": [s(10, 40), s(100, 130)], "after_gates": [s(10, 40)], "offered": [s(10, 40), s(900, 930)]}}
    editors = [{"person": "r", "top10": [s(10, 40)]}]
    row = eh.evaluate_source(report, MOMENTS, editors)
    assert row["angeboten"] == 2 and row["referenzmomente"] == {"gold": 2, "silber": 1}
    agg = eh.aggregate_sources({"q1": row, "q2": eh.evaluate_source(report, MOMENTS, None)})
    assert agg["abdeckung"]["pool"]["alle"]["abgedeckt"] == 4 and agg["abdeckung"]["pool"]["alle"]["gesamt"] == 6
    assert agg["precision"]["p@5"]["wert"] == 0.5 and agg["neue_momente"]["anzahl"] == 2  # je Quelle einer
    m = eh.metrics(agg)
    assert m["abdeckung_nach_gates"]["wert"] == pytest.approx(2 / 6) and m["precision_at_10"]["stichprobe"] == 2
    assert m["grenzfehler_start_s"]["wert"] == 0.0
    no_refs = eh.metrics(eh.aggregate_sources({"q": eh.evaluate_source(report, None, None)}))
    assert no_refs["recall_at_20"] == {"wert": None, "stichprobe": None, "ursache": "keine Referenzmomente"}
    assert no_refs["precision_at_5"]["ursache"] == "keine Redakteurs-Top-10"
    assert no_refs["grenzfehler_gewichtet_s"]["wert"] is None


def test_cut_quality():
    doc = {"schnittpunkte": [{"clip_id": "c1", "zeit_s": 1, "urteil": "natuerlich", "hoerer": "h1"},
                             {"clip_id": "c1", "zeit_s": 9, "urteil": "natuerlich", "hoerer": "h2"},
                             {"clip_id": "c2", "zeit_s": 3, "urteil": "abgehackt", "hoerer": "h1"},
                             {"clip_id": "c3", "zeit_s": 3, "urteil": "zu_lang", "hoerer": "h1"}],
           "clip_urteile": [{"clip_id": "c3", "hoerer": "h2", "urteil": "unbrauchbar"}]}  # fmt: skip
    q = eh.cut_quality(doc)
    assert q["natuerlich_anteil"] == 0.5 and q["je_hoerer"] == {"h1": 1 / 3, "h2": 1.0}
    assert q["clips_unbrauchbar"] == ["c2", "c3"] and q["clips_unbrauchbar_anteil"] == 2 / 3
    empty = eh.cut_quality({})
    assert empty["natuerlich_anteil"] is None and empty["metriken"]["schnitt_natuerlich_anteil"]["ursache"] == "keine Schnittpunkt-Urteile"


def test_run_data_on_example_and_cli(tmp_path, capsys):
    res = eh.run_data(DATA / "beispiel", DATA / "beispiel" / "berichte")
    assert list(res["je_quelle"]) == ["beispiel_debatte"] and "beispiel_debatte_ausschnitt" in res["ohne_bericht"]
    m = res["metriken"]
    assert m["abdeckung_pool"]["wert"] == 1.0 and m["abdeckung_nach_gates"]["wert"] == pytest.approx(2 / 3)
    assert m["abdeckung_top_k"]["wert"] == pytest.approx(1 / 3) and m["schnitt_natuerlich_anteil"]["wert"] == 0.5
    with pytest.raises(Exception, match="abschluss ist gesperrt"):
        eh.run_data(DATA / "beispiel", DATA / "beispiel" / "berichte", part="abschluss")
    out = tmp_path / "h.json"
    eh.main(["--daten", str(DATA / "beispiel"), "--berichte", str(DATA / "beispiel" / "berichte"), "--json", str(out)])
    text = capsys.readouterr().out
    assert "Abdeckung nach Gates      66,7 %" in text and "Neu entdeckte Momente" in text
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["recall_at_20"]["wert"] == pytest.approx(1 / 3)
    with pytest.raises(SystemExit, match="abschluss ist gesperrt"):
        eh.main(["--daten", str(DATA / "beispiel"), "--berichte", str(tmp_path), "--teil", "abschluss"])
    with pytest.raises(SystemExit, match="--daten braucht --berichte"):
        eh.main(["--daten", str(DATA / "beispiel")])
    with pytest.raises(SystemExit, match="Entweder"):
        eh.main([])


def test_run_data_without_reports_is_not_measurable(tmp_path):
    res = eh.run_data(DATA, tmp_path)
    assert res["gesamt"] is None and len(res["ohne_bericht"]) == 20
    assert set(eh.HARNESS_METRICS) <= set(res["metriken"]) and res["metriken"]["recall_at_20"]["ursache"].startswith("keine Quelle im Teil entwicklung")
    assert set(eh.metrics(eh.aggregate_sources({"q": eh.evaluate_source({}, None)}))) == set(eh.HARNESS_METRICS)
    assert "Abdeckung, Recall, Precision und Grenzfehler nicht messbar" in eh.format_data_report(res)


def test_old_cli_still_works(tmp_path, capsys):
    gold, pred = tmp_path / "g", tmp_path / "p"
    gold.mkdir(), pred.mkdir()
    (gold / "e.json").write_text(json.dumps({"dialect": "AT", "clips": [{"start": 0, "end": 10, "rating": 3}]}), encoding="utf-8")
    (pred / "e.json").write_text(json.dumps({"clips": [{"start": 0, "end": 10, "total": 1}]}), encoding="utf-8")
    eh.main([str(gold), str(pred)])
    assert "AT" in capsys.readouterr().out
