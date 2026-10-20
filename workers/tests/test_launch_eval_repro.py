"""Reproduzierbarkeit: Top-5, Jaccard, Rang 1, frische und gespeicherte Läufe."""

from __future__ import annotations

import json

import pytest

from eval import repro_eval as rv


def rep(*spans, funnel=False):
    items = [{"start_s": a, "end_s": b, "total": 10.0 - i} for i, (a, b) in enumerate(spans)]
    if funnel:
        return {"funnel": {"offered": [{**x, "rank": i + 1} for i, x in enumerate(items)]}, "candidates": []}
    return {"candidates": list(reversed(items))}


def test_top_spans_from_candidates_and_funnel():
    assert rv.top_spans(rep((0, 10), (20, 30))) == [(0.0, 10.0), (20.0, 30.0)]
    assert rv.top_spans(rep((5, 6), (1, 2), funnel=True)) == [(5.0, 6.0), (1.0, 2.0)]
    assert rv.top_spans(rep(*[(i, i + 1) for i in range(8)])) == [(float(i), float(i + 1)) for i in range(5)]
    assert rv.top_spans({}) == []


def test_jaccard_exact_and_iou():
    a = [(0.0, 10.0), (20.0, 30.0)]
    assert rv.jaccard(a, a) == 1.0
    assert rv.jaccard(a, [(0.0, 10.0), (50.0, 60.0)]) == pytest.approx(1 / 3)
    assert rv.jaccard(a, [(0.1, 10.0), (20.0, 30.0)]) == pytest.approx(1 / 3)
    assert rv.jaccard(a, [(0.1, 10.0), (20.0, 30.0)], iou=0.8) == 1.0
    assert rv.jaccard([], []) is None and rv.jaccard(a, []) == 0.0


def test_evaluate_fresh_runs():
    base = rep((0, 10), (20, 30), (40, 50), (60, 70), (80, 90))
    same = rep((0, 10), (20, 30), (40, 50), (60, 70), (80, 90))
    swapped = rep((20, 30), (0, 10), (40, 50), (60, 70), (80, 90))
    other = rep((0, 10), (20, 30), (40, 50), (60, 70), (100, 110))
    res = rv.evaluate([base, same, swapped, other])
    assert [r["bestanden"] for r in res["vergleiche"]] == [True, False, False]
    assert res["vergleiche"][2]["jaccard"] == pytest.approx(4 / 6) and res["vergleiche"][1]["rang1_gleich"] is False
    assert res["bestanden_anteil"] == pytest.approx(1 / 3) and res["rang1_gleich_anteil"] == pytest.approx(2 / 3)
    assert res["metriken"]["jaccard_top5_mittel"]["stichprobe"] == 4
    assert "Bestanden: 1 von 3" in rv.format_report(res)


def test_evaluate_stored_runs_must_be_identical():
    base = rep((0, 10), (20, 30))
    swapped = rep((20, 30), (0, 10))
    res = rv.evaluate([base, base, swapped], kind="gespeichert")
    assert [r["bestanden"] for r in res["vergleiche"]] == [True, False]
    assert set(res["metriken"]) == {"jaccard_top5_mittel_gespeichert", "rang1_gleich_anteil_gespeichert", "repro_bestanden_anteil_gespeichert"}
    with pytest.raises(SystemExit, match="--art"):
        rv.evaluate([base], kind="warm")


def test_evaluate_needs_two_runs_and_rounds():
    one = rv.evaluate([rep((0, 10))])
    assert one["bestanden_anteil"] is None and one["metriken"]["rang1_gleich_anteil"]["ursache"] == "mindestens zwei Läufe nötig"
    assert "nicht messbar" in rv.format_report(one)
    jitter = rv.evaluate([rep((0.01, 10.02)), rep((0.02, 9.98))])
    assert jitter["vergleiche"][0]["identisch"] is True


def test_cli(tmp_path, capsys):
    paths = []
    for i in range(3):
        p = tmp_path / f"r{i}.json"
        p.write_text(json.dumps(rep((0, 10), (20, 30))), encoding="utf-8")
        paths.append(str(p))
    out = tmp_path / "repro.json"
    rv.main([*paths, "--json", str(out)])
    assert "Bestanden: 2 von 2" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["metriken"]["repro_bestanden_anteil"]["wert"] == 1.0
