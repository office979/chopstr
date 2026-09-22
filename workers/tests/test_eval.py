from __future__ import annotations

import json

from eval import eval_harness, wer_eval


def test_normalize_and_align():
    ref = wer_eval.normalize("Wir haben 40.000 Euro verloren, weil z. B. keine Rücklagen da waren.")
    assert ref[2] == "40.000" or "40" in ref[2]
    al = wer_eval.align(["a", "b", "c"], ["a", "x", "c", "d"])
    assert (al.sub, al.dele, al.ins) == (1, 0, 1)
    assert al.wer == 2 / 3
    assert wer_eval.align([], []).wer == 0.0


def test_ch_normalization_equates_ss():
    assert wer_eval.normalize("Straße", ch=True) == ["strasse"]
    assert wer_eval.normalize("Straße", ch=False) == ["straße"]


def test_name_error_rate_and_pair():
    r = wer_eval.evaluate_pair("Wir nutzen chopstr täglich", "Wir nutzen Chopster täglich", "AT", ["chopstr"])
    assert r["wer"] == 0.25
    assert r["name_error_rate"] == 1.0 and r["name_total"] == 1
    r2 = wer_eval.evaluate_pair("Wir nutzen chopstr täglich", "wir nutzen chopstr täglich.", "DE", ["chopstr"])
    assert r2["wer"] == 0.0 and r2["name_error_rate"] == 0.0


def test_run_over_folders(tmp_path):
    gold, hyp = tmp_path / "gold", tmp_path / "hyp"
    gold.mkdir(), hyp.mkdir()
    (gold / "ep1.json").write_text(json.dumps({"dialect": "AT", "text": "Das ist ein Test", "names": []}), encoding="utf-8")
    (hyp / "ep1.json").write_text(json.dumps({"words": [{"text": "Das"}, {"text": "ist"}, {"text": "Test"}]}), encoding="utf-8")
    (gold / "ep2_CH.txt").write_text("Die Strasse ist grün", encoding="utf-8")
    (hyp / "ep2_CH.txt").write_text("Die Straße ist grün", encoding="utf-8")
    res = wer_eval.run(str(gold), str(hyp))
    assert res["summary"]["AT"]["wer"] == 0.25
    assert res["summary"]["CH"]["wer"] == 0.0
    table = wer_eval.format_table(res["summary"])
    assert "AT" in table and "CH" in table


def test_eval_harness_metrics():
    gold = {"dialect": "DE", "clips": [{"start": 10, "end": 40, "rating": 3}, {"start": 100, "end": 130, "rating": 1}]}
    pred = {"clips": [{"start": 12, "end": 41, "total": 9}, {"start": 500, "end": 520, "total": 8}]}
    r = eval_harness.evaluate(gold, pred, k=10)
    assert r["precision_at_k"] == 0.5
    assert r["recall"] == 1.0
    assert r["boundary_err_s"] == 1.5
    assert eval_harness.iou({"start": 0, "end": 10}, {"start": 5, "end": 15}) == 1 / 3
