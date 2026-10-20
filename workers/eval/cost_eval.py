"""Kosten (EUR) und Laufzeit je Quellstunde aus ``job_costs``.

    .venv/bin/python -m eval.cost_eval --export kosten.json [--json kosten_ergebnis.json]
    .venv/bin/python -m eval.cost_eval --database-url postgresql://... --quelle <uuid> [--quelle <uuid>]

Eingabe ist ein JSON-Export ``{"job_costs": [...], "sources": [{"id", "duration_s"}], "laufzeiten": [...]}``
(oder nur die Liste der ``job_costs``-Zeilen) oder die Datenbank, die ausschließlich über ``--database-url``
erreicht wird, nie implizit über die Umgebung. ``laufzeiten`` ist optional: je Quelle ``wartezeit_s`` (Upload bis
Kandidatenliste, Wanduhr), ``cache`` (kalt oder warm), ``hardware`` und ``gerenderte_clips``.

Gerechnet wird je Quelle und über alle Quellen: EUR (Summe ``estimated_eur``), Rechenzeit (CPU plus GPU
Sekunden) und, wenn vorhanden, Wartezeit, jeweils geteilt durch die Quelldauer in Stunden (``sources.duration_s``,
sonst ``source_minutes`` der Ingest-Zeile). Ohne Quelldauer ist der Wert nicht messbar.

Hinweis: ``estimated_eur`` stammt aus der Preistabelle in ``chopstr_worker/costlog.py``; deren Standardwerte sind
Platzhalter, keine Anbieterpreise. Der Bericht nennt das.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

PRICE_NOTE = "EUR sind Schätzungen aus der Preistabelle (costlog.py); ohne gesetzte Preise sind es Platzhalterwerte."
SQL_COSTS = (
    "select source_id::text, job_type, provider, model_id, source_minutes, gpu_seconds, cpu_seconds, estimated_eur "
    "from job_costs where source_id = any(%s::uuid[])"
)
SQL_SOURCES = "select id::text, duration_s from sources where id = any(%s::uuid[])"
COST_COLUMNS = ("source_id", "job_type", "provider", "model_id", "source_minutes", "gpu_seconds", "cpu_seconds", "estimated_eur")


def _f(value: Any) -> float:
    return 0.0 if value is None else float(value)


def load_from_db(conn: Any, source_ids: list[str]) -> dict[str, Any]:
    """Export-Format aus der Datenbank (``conn`` mit ``execute(...).fetchall()``)."""
    rows = conn.execute(SQL_COSTS, (source_ids,)).fetchall()
    sources = conn.execute(SQL_SOURCES, (source_ids,)).fetchall()
    return {
        "job_costs": [dict(zip(COST_COLUMNS, r)) for r in rows],
        "sources": [{"id": sid, "duration_s": None if dur is None else float(dur)} for sid, dur in sources],
    }


def normalize_export(doc: Any) -> dict[str, Any]:
    if isinstance(doc, list):
        return {"job_costs": doc, "sources": [], "laufzeiten": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("job_costs"), list):
        raise SystemExit("Export: erwartet eine Liste von job_costs-Zeilen oder {\"job_costs\": [...]}.")
    return {"job_costs": doc["job_costs"], "sources": doc.get("sources") or [], "laufzeiten": doc.get("laufzeiten") or []}


def source_hours(source_id: str, durations: dict[str, float | None], rows: list[dict]) -> tuple[float | None, str | None]:
    dur = durations.get(source_id)
    if dur:
        return dur / 3600.0, "sources.duration_s"
    minutes = [_f(r.get("source_minutes")) for r in rows if r.get("job_type") == "ingest" and _f(r.get("source_minutes")) > 0]
    if minutes:
        return max(minutes) / 60.0, "job_costs.source_minutes (ingest)"
    return None, None


def evaluate(export: dict[str, Any]) -> dict[str, Any]:
    exp = normalize_export(export)
    by_source: dict[str, list[dict]] = defaultdict(list)
    without_source = 0
    for r in exp["job_costs"]:
        if r.get("source_id"):
            by_source[str(r["source_id"])].append(r)
        else:
            without_source += 1
    durations = {str(s["id"]): (None if s.get("duration_s") is None else float(s["duration_s"])) for s in exp["sources"]}
    walls = {str(w["source_id"]): w for w in exp["laufzeiten"] if w.get("source_id")}
    per: dict[str, dict[str, Any]] = {}
    for sid, rows in sorted(by_source.items()):
        hours, origin = source_hours(sid, durations, rows)
        eur = sum(_f(r.get("estimated_eur")) for r in rows)
        compute = sum(_f(r.get("cpu_seconds")) + _f(r.get("gpu_seconds")) for r in rows)
        by_type: dict[str, dict[str, float]] = defaultdict(lambda: {"eur": 0.0, "rechenzeit_s": 0.0})
        for r in rows:
            t = by_type[str(r.get("job_type") or "ohne_typ")]
            t["eur"] += _f(r.get("estimated_eur"))
            t["rechenzeit_s"] += _f(r.get("cpu_seconds")) + _f(r.get("gpu_seconds"))
        wall = walls.get(sid) or {}
        wait = wall.get("wartezeit_s")
        per[sid] = {
            "quell_stunden": hours, "dauer_herkunft": origin, "eur": round(eur, 4), "rechenzeit_s": round(compute, 2),
            "eur_je_quellstunde": None if not hours else eur / hours,
            "rechenzeit_s_je_quellstunde": None if not hours else compute / hours,
            "wartezeit_s": wait, "wartezeit_s_je_quellstunde": None if not hours or wait is None else float(wait) / hours,
            "cache": wall.get("cache"), "hardware": wall.get("hardware"), "gerenderte_clips": wall.get("gerenderte_clips"),
            "je_job_typ": {k: {"eur": round(v["eur"], 4), "rechenzeit_s": round(v["rechenzeit_s"], 2)} for k, v in sorted(by_type.items())},
            "ursache": None if hours else "Quelldauer unbekannt (weder sources.duration_s noch ingest.source_minutes)",
        }  # fmt: skip
    known = [p for p in per.values() if p["quell_stunden"]]
    hours = sum(p["quell_stunden"] for p in known)
    timed = [p for p in known if p["wartezeit_s"] is not None]
    timed_hours = sum(p["quell_stunden"] for p in timed)
    total = {
        "quellen": len(per), "quellen_mit_dauer": len(known), "quell_stunden": hours or None,
        "eur_je_quellstunde": sum(p["eur"] for p in known) / hours if hours else None,
        "rechenzeit_s_je_quellstunde": sum(p["rechenzeit_s"] for p in known) / hours if hours else None,
        "wartezeit_s_je_quellstunde": sum(float(p["wartezeit_s"]) for p in timed) / timed_hours if timed_hours else None,
        "zeilen_ohne_quelle": without_source,
    }  # fmt: skip
    res = {"je_quelle": per, "gesamt": total, "hinweis": PRICE_NOTE}
    res["metriken"] = metrics(res)
    return res


def metrics(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    g = res["gesamt"]
    no_hours = "keine Quelle mit bekannter Dauer" if g["quellen"] else "keine job_costs-Zeilen mit Quelle"
    return {
        "eur_je_quellstunde": {"wert": g["eur_je_quellstunde"], "stichprobe": g["quellen_mit_dauer"], "ursache": None if g["eur_je_quellstunde"] is not None else no_hours},
        "rechenzeit_s_je_quellstunde": {"wert": g["rechenzeit_s_je_quellstunde"], "stichprobe": g["quellen_mit_dauer"], "ursache": None if g["rechenzeit_s_je_quellstunde"] is not None else no_hours},
        "wartezeit_s_je_quellstunde": {"wert": g["wartezeit_s_je_quellstunde"], "stichprobe": g["quellen_mit_dauer"],
                                       "ursache": None if g["wartezeit_s_je_quellstunde"] is not None else "keine Wartezeiten im Export (laufzeiten fehlt)"},
    }  # fmt: skip


def _num(value: float | None, unit: str, cause: str | None = None) -> str:
    return f"nicht messbar: {cause or 'keine Daten'}" if value is None else f"{value:.2f} {unit}".replace(".", ",")


def format_report(res: dict[str, Any]) -> str:
    lines = []
    for sid, p in res["je_quelle"].items():
        lines.append(f"{sid}: {_num(p['eur_je_quellstunde'], 'EUR je Quellstunde', p['ursache'])}, "
                     f"Rechenzeit {_num(p['rechenzeit_s_je_quellstunde'], 's je Quellstunde', p['ursache'])}")  # fmt: skip
    m = res["metriken"]
    lines.append(f"Gesamt: {_num(m['eur_je_quellstunde']['wert'], 'EUR je Quellstunde', m['eur_je_quellstunde']['ursache'])}; "
                 f"Rechenzeit {_num(m['rechenzeit_s_je_quellstunde']['wert'], 's je Quellstunde', m['rechenzeit_s_je_quellstunde']['ursache'])}; "
                 f"Wartezeit {_num(m['wartezeit_s_je_quellstunde']['wert'], 's je Quellstunde', m['wartezeit_s_je_quellstunde']['ursache'])}")  # fmt: skip
    lines.append(res["hinweis"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Kosten und Laufzeit je Quellstunde aus job_costs.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--export", help="JSON-Export mit job_costs, sources und optional laufzeiten")
    src.add_argument("--database-url", help="Postgres-URL; nur so greift das Werkzeug auf eine Datenbank zu")
    ap.add_argument("--quelle", action="append", default=[], help="UUID einer Quelle (mit --database-url), mehrfach")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    if args.export:
        export = json.loads(Path(args.export).read_text(encoding="utf-8"))
    else:
        if not args.quelle:
            raise SystemExit("--database-url braucht mindestens eine --quelle.")
        from chopstr_worker import db

        conn = db.connect(args.database_url)
        try:
            export = load_from_db(conn, args.quelle)
        finally:
            conn.close()
    res = evaluate(export)
    print(format_report(res))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
