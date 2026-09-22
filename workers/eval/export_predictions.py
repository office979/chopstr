"""Exportiert die Kandidaten einer Quelle als Vorhersage-Datei für ``eval_harness.py`` (Blindtest, Precision@10).

Quelle der Kandidaten:
  - Postgres (``--source-id`` plus ``--db`` oder ``DATABASE_URL``): Tabelle ``candidates``
  - oder das Ergebnis-JSON der Story-Engine aus dem Storage (``--json``; Key ``candidates/<hash>.json``,
    der ``finished``-Payload von ``detect_candidates`` nennt ihn unter ``key``)

Ausgabe: ``{"episode": "<name>", "clips": [{"start": ..., "end": ..., "total": ...}]}``.

Aufruf:
  python -m eval.export_predictions --source-id <uuid> --episode ep01.mp4 --out preds/ep01.json
  python -m eval.export_predictions --json storage/chopstr-derived/candidates/<hash>.json --episode ep01.mp4 --out preds/ep01.json

Optionen: ``--only-gate-passed`` (nur Kandidaten ohne Einwand), ``--include-rejected`` (auch abgelehnte).
Standard: alle Kandidaten außer ``human_verdict = 'rejected'``; sortiert nach ``total`` absteigend.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


def to_prediction(episode: str, rows: list[dict[str, Any]], only_gate_passed: bool = False, include_rejected: bool = False) -> dict:
    """Zeilen (``start_s``, ``end_s``, ``total``, optional ``gate_passed``, ``human_verdict``) zur Vorhersage-Datei."""
    clips = []
    for r in rows:
        if only_gate_passed and not r.get("gate_passed", True):
            continue
        if not include_rejected and r.get("human_verdict") == "rejected":
            continue
        clips.append({"start": float(r["start_s"]), "end": float(r["end_s"]), "total": float(r.get("total") or 0.0)})
    clips.sort(key=lambda c: (-c["total"], c["start"]))
    return {"episode": episode, "clips": clips}


def rows_from_json(path: str | os.PathLike) -> list[dict[str, Any]]:
    """Ergebnis-JSON der Story-Engine (``DetectReport.to_json``) oder eine Liste von Zeilen."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("candidates", []) if isinstance(data, dict) else data
    return [dict(r) for r in rows]


def rows_from_db(dsn: str, source_id: str) -> list[dict[str, Any]]:
    """Kandidaten aus Postgres; ``psycopg`` wird erst hier importiert."""
    from chopstr_worker import db

    conn = db.connect(dsn)
    try:
        rows = db.fetch_all(
            conn,
            "select start_s, end_s, total, gate_passed, human_verdict from candidates where source_id = %s order by total desc",
            (source_id,),
        )
    finally:
        conn.close()
    keys = ("start_s", "end_s", "total", "gate_passed", "human_verdict")
    return [dict(zip(keys, r)) for r in rows]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Kandidaten einer Quelle als Vorhersage-Datei für eval_harness exportieren")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-id", help="sources.id (liest aus Postgres)")
    src.add_argument("--json", dest="json_path", help="Ergebnis-JSON der Story-Engine aus dem Storage")
    ap.add_argument("--db", default=os.environ.get("DATABASE_URL", ""), help="Postgres-DSN (Default: DATABASE_URL)")
    ap.add_argument("--episode", required=True, help="Episodenname wie in der Gold-Datei, z. B. ep01.mp4")
    ap.add_argument("--out", required=True, help="Zieldatei, z. B. preds/ep01.json")
    ap.add_argument("--only-gate-passed", action="store_true")
    ap.add_argument("--include-rejected", action="store_true")
    args = ap.parse_args(argv)

    if args.json_path:
        rows = rows_from_json(args.json_path)
    else:
        if not args.db:
            raise SystemExit("Kein Postgres-DSN: --db setzen oder DATABASE_URL exportieren")
        rows = rows_from_db(args.db, args.source_id)
    pred = to_prediction(args.episode, rows, args.only_gate_passed, args.include_rejected)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pred, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(pred['clips'])} Clips nach {out} geschrieben")


if __name__ == "__main__":
    main()
