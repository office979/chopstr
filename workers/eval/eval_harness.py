"""Eval-Harness: Wie nah kommt die Maschine an die Redakteur:innen?

Gold-Datei (JSON pro Episode):
  {"episode": "ep01.mp4", "dialect": "AT", "clips": [{"start": 812.4, "end": 861.0, "rating": 3}]}
  rating: 3 = würde sofort posten, 2 = mit Nacharbeit, 1 = Notlösung
Vorhersage-Datei: {"episode": "ep01.mp4", "clips": [{"start":..., "end":..., "total":...}]}

Metriken:
- Precision@k: Anteil der Top-k-Vorschläge, die mit einem Gold-Clip überlappen (IoU >= 0.5)
- Recall: Anteil der Gold-Clips (rating >= 2), die gefunden wurden
- Boundary-Error: mittlere Abweichung Start/Ende in Sekunden (misst „schneidet mitten im Gedanken")
- Pro Dialekt ausgewertet (AT/DE/CH), damit Dialekt-Schwächen sichtbar werden
Aufruf: python -m eval.eval_harness gold/ preds/ --k 10 [--json out.json]
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

IOU_MATCH = 0.5


def iou(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / union if union > 0 else 0.0


def evaluate(gold: dict, pred: dict, k: int) -> dict:
    top = sorted(pred["clips"], key=lambda c: c.get("total", 0), reverse=True)[:k]
    good_gold = [g for g in gold["clips"] if g.get("rating", 1) >= 2]
    hits, boundary = 0, []
    for p in top:
        best = max(good_gold, key=lambda g: iou(p, g), default=None)
        if best and iou(p, best) >= IOU_MATCH:
            hits += 1
            boundary.append((abs(p["start"] - best["start"]) + abs(p["end"] - best["end"])) / 2)
    found = sum(1 for g in good_gold if any(iou(p, g) >= IOU_MATCH for p in top))
    return {
        "precision_at_k": hits / max(len(top), 1),
        "recall": found / max(len(good_gold), 1),
        "boundary_err_s": sum(boundary) / len(boundary) if boundary else None,
        "n_pred": len(top),
        "n_gold": len(good_gold),
    }


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    be = [x["boundary_err_s"] for x in rows if x["boundary_err_s"] is not None]
    return {
        "n": n,
        "precision_at_k": sum(r["precision_at_k"] for r in rows) / n if n else 0.0,
        "recall": sum(r["recall"] for r in rows) / n if n else 0.0,
        "boundary_err_s": sum(be) / len(be) if be else None,
    }


def run(gold_dir: str, pred_dir: str, k: int) -> dict[str, dict]:
    by_dialect: dict[str, list[dict]] = defaultdict(list)
    for gf in sorted(Path(gold_dir).glob("*.json")):
        gold = json.loads(gf.read_text(encoding="utf-8"))
        pf = Path(pred_dir) / gf.name
        if not pf.exists():
            continue
        res = evaluate(gold, json.loads(pf.read_text(encoding="utf-8")), k)
        by_dialect[gold.get("dialect", "?")].append(res)
    return {d: aggregate(rows) for d, rows in sorted(by_dialect.items())}


def format_table(summary: dict[str, dict], k: int) -> str:
    lines = [f"{'Dialekt':8} {'n':>4} {'P@' + str(k):>7} {'Recall':>7} {'Boundary':>9}"]
    for d, agg in summary.items():
        be = f"{agg['boundary_err_s']:.1f}s" if agg["boundary_err_s"] is not None else "-"
        lines.append(f"{d:8} {agg['n']:>4} {agg['precision_at_k']:>7.2f} {agg['recall']:>7.2f} {be:>9}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gold_dir")
    ap.add_argument("pred_dir")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)
    summary = run(args.gold_dir, args.pred_dir, args.k)
    print(format_table(summary, args.k))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
