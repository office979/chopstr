"""Baseline: Zusammenführen der Messungen, Urteil je Metrik mit Toleranz, Bericht, CLI, Testmaterial-Messung."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval import baseline as bl

RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"


def doc(**metrics):
    return {"metriken": {k: (v if isinstance(v, dict) else {"wert": v, "stichprobe": 10, "ursache": None}) for k, v in metrics.items()}}


def test_merge_measurements_rules():
    merged = bl.merge_measurements([("a.json", doc(cpwer=0.1)), ("b.json", doc(der={"wert": None, "ursache": "keine Referenz"}))])
    assert merged["cpwer"]["herkunft"] == "a.json" and merged["der"]["ursache"] == "keine Referenz"
    assert bl.merge_measurements([("c.json", doc(der={"wert": None}))])["der"]["ursache"] == "keine Ursache angegeben"
    with pytest.raises(SystemExit, match="nicht registriert"):
        bl.merge_measurements([("a.json", doc(phantasie=1.0))])
    with pytest.raises(SystemExit, match="steht auch in a.json"):
        bl.merge_measurements([("a.json", doc(cpwer=0.1)), ("b.json", doc(cpwer=0.2))])
    with pytest.raises(SystemExit, match="metriken fehlt"):
        bl.merge_measurements([("a.json", {})])


def test_make_baseline_fills_every_metric():
    base = bl.make_baseline([("m.json", {**doc(cpwer=0.1), "provider": "p"})], None, "clip_policy_v2", "M2", "2026-10-20")
    assert set(base["metriken"]) == set(bl.METRICS)
    assert base["metriken"]["cpwer"]["wert"] == 0.1 and base["metriken"]["cpwer"]["richtung"] == bl.LOWER
    assert base["metriken"]["der"]["wert"] is None and base["metriken"]["der"]["ursache"].startswith("nicht gemessen")
    assert (base["provider"], base["policy"], base["hardware"]) == ("p", "clip_policy_v2", "M2")


def test_judge_directions_and_tolerance():
    hi = {"richtung": bl.HIGHER, "toleranz": 0.05}
    lo = {"richtung": bl.LOWER, "toleranz": 10}
    assert bl.judge(hi, 0.80, 0.76) == "ok" and bl.judge(hi, 0.80, 0.74) == "verschlechtert"
    assert bl.judge(hi, 0.80, 0.75) == "ok"  # genau an der Toleranz
    assert bl.judge(lo, 50, 60) == "ok" and bl.judge(lo, 50, 61) == "verschlechtert"
    assert bl.judge(lo, None, 1) == "nicht messbar" and bl.judge(lo, 1, None) == "nicht messbar"
    assert bl.judge({"richtung": bl.INFO, "toleranz": None}, 1, 99) == "ok"


def test_compare_and_report(tmp_path):
    base = bl.make_baseline([("m.json", doc(cpwer=0.10, precision_at_5=0.6))], "p", "v2", "M2", "2026-10-20")
    rows = {r["metrik"]: r for r in bl.compare(base, [("neu.json", doc(cpwer=0.15, precision_at_5=0.58, der=0.2))])}
    assert rows["cpwer"]["urteil"] == "verschlechtert" and rows["cpwer"]["differenz"] == pytest.approx(0.05)
    assert rows["precision_at_5"]["urteil"] == "ok"
    assert rows["der"]["urteil"] == "nicht messbar" and rows["der"]["ursache"].startswith("Baseline: nicht gemessen")
    text = bl.report_markdown(list(rows.values()), base, "Test", "2026-10-21", ["neu.json"])
    assert "| cpwer | 10,0 % | 15,0 % | +5,0 Punkte | 1,0 Punkte | verschlechtert |" in text
    assert "**Ergebnis: verschlechtert, blockiert den Merge**" in text
    assert "—" not in text and "–" not in text


def test_slug():
    assert bl.slug("Neue Satzregel für Österreich") == "neue-satzregel-fuer-oesterreich"
    with pytest.raises(SystemExit):
        bl.slug("!!!")


def test_write_comparison_needs_baseline(tmp_path):
    with pytest.raises(SystemExit, match="erst --erstellen"):
        bl.write_comparison(tmp_path / "fehlt.json", [], "x", "2026-10-21", tmp_path)


def test_cli_round_trip(tmp_path, capsys):
    m1 = tmp_path / "m1.json"
    m1.write_text(json.dumps(doc(cpwer=0.10)), encoding="utf-8")
    base = tmp_path / "baseline.json"
    assert bl.main(["--erstellen", str(m1), "--out", str(base), "--provider", "local-heuristic", "--datum", "2026-10-20"]) == 0
    assert "1 von" in capsys.readouterr().out
    good = tmp_path / "good.json"
    good.write_text(json.dumps(doc(cpwer=0.105)), encoding="utf-8")
    assert bl.main(["--vergleich", str(good), "--aenderung", "kleiner Schritt", "--baseline", str(base), "--ziel", str(tmp_path), "--datum", "2026-10-21"]) == 0
    assert (tmp_path / "2026-10-21-kleiner-schritt.md").is_file()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc(cpwer=0.2)), encoding="utf-8")
    assert bl.main(["--vergleich", str(bad), "--aenderung", "x", "--baseline", str(base), "--ziel", str(tmp_path)]) == 1
    assert "Verschlechtert über der Toleranz: cpwer" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="--aenderung"):
        bl.main(["--vergleich", str(good), "--baseline", str(base)])
    with pytest.raises(SystemExit, match="fehlt"):
        bl.main(["--erstellen", str(tmp_path / "nichts.json"), "--out", str(base)])
    with pytest.raises(SystemExit, match="--out"):
        bl.main(["--messen-testmaterial", str(tmp_path)])


def test_measure_testmaterial_on_a_small_fixture(tmp_path):
    folder = tmp_path / "gespraech"
    folder.mkdir()
    (tmp_path / "transkripte").mkdir()
    gt = {"saetze": [{"sprecher": "S0", "text": "Guten Tag zusammen.", "start": 1.0, "end": 2.5}], "turns": []}
    (folder / "sprecherwechsel.json").write_text(json.dumps(gt), encoding="utf-8")
    words = [{"text": "Guten", "start": 0.9, "end": 1.3}, {"text": "Tag", "start": 1.3, "end": 1.8}, {"text": "zusammen", "start": 1.8, "end": 2.4}]
    (tmp_path / "transkripte" / "gespraech.json").write_text(json.dumps({"words": words}), encoding="utf-8")
    m = bl.measure_testmaterial(tmp_path)["metriken"]
    assert m["wer_de_synthetisch"]["wert"] == 0.0 and m["wer_de_synthetisch"]["stichprobe"] == 3
    assert m["versatz_anfang_median_synthetisch_ms"]["wert"] == pytest.approx(100.0)
    assert m["versatz_ende_median_synthetisch_ms"]["wert"] == pytest.approx(100.0)
    assert m["der"]["wert"] is None and "Montage" in m["der"]["ursache"]
    empty = bl.measure_testmaterial(tmp_path / "leer")["metriken"]
    assert empty["wer_de_synthetisch"]["wert"] is None and "kein Gespräch" in empty["wer_de_synthetisch"]["ursache"]
    out = tmp_path / "m.json"
    assert bl.main(["--messen-testmaterial", str(tmp_path), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["wer_de_synthetisch"]["wert"] == 0.0


def test_versioned_baseline_file_is_complete():
    base = json.loads((RESULTS / "baseline.json").read_text(encoding="utf-8"))
    assert set(base["metriken"]) == set(bl.METRICS)
    for name, m in base["metriken"].items():
        assert (m["wert"] is None) == bool(m["ursache"]), name
        assert {"einheit", "richtung", "toleranz", "stichprobe"} <= set(m), name


def _report(offered=2, hours=0.5, distinct=1, states=("passed", "uncertain"), counts=None, discarded=None, with_yield=True):
    rep = {"candidates": [{"start_s": i, "end_s": i + 1, **({"rubric": {"review_state": st}} if st else {})} for i, st in enumerate(states)]}
    if with_yield:
        rep["yield"] = {"offered": offered, "viable_per_source_hour": offered / hours, "distinct": distinct, "distinct_jaccard": 0.6, "source_hours": hours}
    if counts is not None:
        rep["funnel_counts"] = counts
    if discarded is not None:
        rep["discarded"] = discarded
    return rep


def test_yield_of_report_fields_and_causes():
    y = bl.yield_of_report(_report(counts={"pool": 10, "pool_reasons": {"gate": 3, "overlap": 1}}))
    assert (y["stunden"], y["angeboten"], y["verschieden"], y["verwendbar"]) == (0.5, 2, 1, 1)
    assert y["gruende"] == {"gate": 3, "overlap": 1} and y["nenner"] == 10 and y["gruende_herkunft"] == "funnel_counts"
    no_state = bl.yield_of_report(_report(states=("passed", None)))
    assert no_state["verwendbar"] is None and "review_state fehlt" in no_state["verwendbar_ursache"]
    assert bl.yield_of_report(_report(offered=0, states=()))["verwendbar"] == 0
    missing = bl.yield_of_report(_report(with_yield=False))
    assert missing["angeboten"] is None and missing["ursache"] == "yield fehlt im Bericht" and missing["gruende"] is None
    assert bl.yield_of_report({"yield": {"offered": 1, "source_hours": 0}})["ursache"].startswith("yield.source_hours")
    disc = bl.yield_of_report(_report(discarded=[{"reason": "gate"}, {"reason": "budget_exhausted"}, {}]))
    assert disc["gruende"] == {"gate": 1, "ohne_grund": 1} and disc["nenner"] == 4 and disc["gruende_herkunft"] == "discarded"


def test_measure_yield_per_source_hour_and_reasons():
    m = bl.measure_yield([("a", _report(counts={"pool": 10, "pool_reasons": {"gate": 3}})),
                          ("b", _report(offered=4, hours=1.5, distinct=3, states=("passed",) * 4, counts={"pool": 10, "pool_reasons": {"gate": 1, "too long": 1}}))])["metriken"]  # fmt: skip
    assert m["angeboten_je_quellstunde"]["wert"] == pytest.approx(6 / 2.0) and m["verwendbare_je_quellstunde"]["wert"] == pytest.approx(5 / 2.0)
    assert m["verschiedene_je_quellstunde"]["wert"] == pytest.approx(4 / 2.0) and m["verschiedene_je_quellstunde"]["stichprobe"] == 2
    assert m["verwerfungsquote_gesamt"]["wert"] == pytest.approx(5 / 20) and m["verwerfungsquote_gate"]["wert"] == pytest.approx(4 / 20)
    assert m["verwerfungsquote_too_long"]["wert"] == pytest.approx(1 / 20)
    partial = bl.measure_yield([("a", _report()), ("b", _report(states=(None, None)))])["metriken"]
    assert partial["verwendbare_je_quellstunde"]["wert"] is None and partial["verwendbare_je_quellstunde"]["ursache"].startswith("b: review_state fehlt")
    assert partial["angeboten_je_quellstunde"]["wert"] == pytest.approx(4 / 1.0)
    none = bl.measure_yield([("a", {"candidates": []})])["metriken"]
    assert none["angeboten_je_quellstunde"]["ursache"] == "a: yield fehlt im Bericht"
    assert none["verwerfungsquote_gesamt"]["ursache"] == "funnel_counts und discarded fehlen im Bericht"
    assert bl.measure_yield([])["metriken"]["verwerfungsquote_gesamt"]["ursache"] == "keine Berichte"


def test_reason_metrics_join_baseline_and_comparison(tmp_path):
    first = bl.measure_yield([("a", _report(counts={"pool": 10, "pool_reasons": {"gate": 2}}))])
    base = bl.make_baseline([("y.json", first)], None, None, None, "2026-10-20")
    assert base["metriken"]["verwerfungsquote_gate"]["richtung"] == bl.INFO and set(bl.METRICS) <= set(base["metriken"])
    second = bl.measure_yield([("a", _report(states=("uncertain", "uncertain"), counts={"pool": 10, "pool_reasons": {"overlap": 4}}))])
    rows = {r["metrik"]: r for r in bl.compare(base, [("neu.json", second)])}
    assert rows["verwerfungsquote_gate"]["urteil"] == "nicht messbar" and rows["verwerfungsquote_overlap"]["urteil"] == "nicht messbar"
    assert rows["verwendbare_je_quellstunde"]["urteil"] == "verschlechtert" and rows["angeboten_je_quellstunde"]["urteil"] == "ok"
    text = bl.report_markdown(list(rows.values()), base, "x", "2026-10-21", ["neu.json"])
    assert "| verwendbare_je_quellstunde | 2,00 je Quellstunde | 0,00 je Quellstunde |" in text
    assert bl.spec_for("verwerfungsquote_") is None and bl.spec_for("unbekannt") is None
    paths = []
    for i, r in enumerate((_report(), _report())):
        p = tmp_path / f"r{i}.json"
        p.write_text(json.dumps(r), encoding="utf-8")
        paths.append(str(p))
    out = tmp_path / "ausbeute.json"
    assert bl.main(["--messen-ausbeute", *paths, "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["angeboten_je_quellstunde"]["wert"] == pytest.approx(4.0)
    with pytest.raises(SystemExit, match="--out"):
        bl.main(["--messen-ausbeute", *paths])


def test_yield_reads_review_state_as_object_from_the_real_contract():
    """Lane P3 schreibt ``rubric.review_state`` als Objekt ``{"state", "reasons", "repair"}``; der echte Lauf
    vom 20.10.2026 zählte deshalb 0 verwendbare Kandidaten, obwohl einer ``passed`` war."""
    from eval import baseline

    rep = _report(states=({"state": "passed", "reasons": [], "repair": {"attempted": False}}, {"state": "uncertain", "reasons": [{"code": "flag:claim"}]}))
    out = baseline.yield_of_report(rep)
    assert out["verwendbar"] == 1 and out.get("verwendbar_ursache") is None
