"""Reproduzierbarkeit der Top-5: Jaccard und gleicher Rang 1 über n Läufe desselben Videos mit demselben Briefing.

    .venv/bin/python -m eval.repro_eval lauf1.json lauf2.json ... [--art frisch|gespeichert] [--json repro.json]

Eingabe sind n DetectReport-JSONs (``story_engine.DetectReport.to_json``). Top-5 je Lauf: ``funnel.offered`` in
Rangfolge, sonst ``candidates`` nach ``total``. Ein Kandidat ist seine Spanne, auf ``--runden`` Sekunden gerundet
(Standard 0,1 s); mit ``--iou 0.8`` gelten zwei Spannen ab dieser Überdeckung als derselbe Kandidat.

Verglichen wird jeder weitere Lauf mit dem ersten (Bezugslauf). Ein Lauf besteht, wenn Jaccard >= 0,8 und Rang 1
gleich ist (Launch-Kriterium: in mindestens 4 von 5 frischen Läufen). Zusätzlich der mittlere Jaccard über alle
Paare. Rang 1 allein und Jaccard allein werden getrennt ausgewiesen, weil Jaccard die Rangfolge ignoriert.

Frische Läufe brauchen umgangenen Cache: den Worker mit ``CHOPSTR_ANALYZE_NO_CACHE=1`` starten (siehe
``chopstr_worker/activities/analyze.py``). Gespeicherte Wiederholungen (Cache-Treffer) mit ``--art gespeichert``
auswerten: dort muss die Top-5 identisch sein, gleiche Spannen in gleicher Reihenfolge.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

from eval import data_loader

TOP_N = 5
JACCARD_MIN = 0.8
DEFAULT_ROUND_S = 0.1
KINDS = ("frisch", "gespeichert")


def top_spans(report: dict[str, Any], n: int = TOP_N) -> list[tuple[float, float]]:
    funnel = report.get("funnel")
    if isinstance(funnel, dict) and isinstance(funnel.get("offered"), list):
        items = funnel["offered"]
        if items and all("rank" in x for x in items):
            items = sorted(items, key=lambda x: x["rank"])
    else:
        items = sorted(report.get("candidates") or [], key=lambda c: c.get("total") or 0.0, reverse=True)
    return [(float(c["start_s"]), float(c["end_s"])) for c in items[:n]]


def _rounded(spans: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    return [(round(round(a / step) * step, 6), round(round(b / step) * step, 6)) for a, b in spans]


def _same(a: tuple[float, float], b: tuple[float, float], iou: float | None) -> bool:
    if iou is None:
        return a == b
    return data_loader.span_iou({"start_s": a[0], "end_s": a[1]}, {"start_s": b[0], "end_s": b[1]}) >= iou


def jaccard(a: list[tuple[float, float]], b: list[tuple[float, float]], iou: float | None = None) -> float | None:
    """Schnittmenge durch Vereinigung; mit ``iou`` werden Kandidaten gierig einander zugeordnet. Zwei leere
    Listen ergeben ``None`` (nichts zu vergleichen)."""
    if not a and not b:
        return None
    used: set[int] = set()
    common = 0
    for x in a:
        j = next((j for j, y in enumerate(b) if j not in used and _same(x, y, iou)), None)
        if j is not None:
            used.add(j)
            common += 1
    union = len(a) + len(b) - common
    return common / union if union else None


def evaluate(reports: list[dict[str, Any]], kind: str = "frisch", step: float = DEFAULT_ROUND_S, iou: float | None = None,
             n: int = TOP_N, threshold: float = JACCARD_MIN) -> dict[str, Any]:  # fmt: skip
    if kind not in KINDS:
        raise SystemExit(f"--art {kind!r}: erlaubt sind {', '.join(KINDS)}.")
    tops = [_rounded(top_spans(r, n), step) for r in reports]
    if len(tops) < 2:
        short = {"art": kind, "laeufe": len(tops), "vergleiche": [], "jaccard_mittel_paarweise": None, "bestanden": None,
                 "bestanden_anteil": None, "rang1_gleich_anteil": None, "ursache": "mindestens zwei Läufe nötig", "top": tops}  # fmt: skip
        short["metriken"] = metrics(short)
        return short
    ref = tops[0]
    rows = []
    for i, t in enumerate(tops[1:], start=2):
        jac = jaccard(ref, t, iou)
        rank1 = bool(ref and t and _same(ref[0], t[0], iou))
        identical = ref == t
        ok = identical if kind == "gespeichert" else (jac is not None and jac >= threshold and rank1)
        rows.append({"lauf": i, "jaccard": jac, "rang1_gleich": rank1, "identisch": identical, "bestanden": ok})
    pair_j = [jaccard(a, b, iou) for a, b in itertools.combinations(tops, 2)]
    pair_j = [x for x in pair_j if x is not None]
    passed = sum(1 for r in rows if r["bestanden"])
    res = {
        "art": kind, "laeufe": len(tops), "bezug": 1, "regel": "identisch" if kind == "gespeichert" else f"Jaccard >= {threshold} und gleicher Rang 1",
        "vergleiche": rows, "bestanden": passed, "bestanden_anteil": passed / len(rows),
        "rang1_gleich_anteil": sum(1 for r in rows if r["rang1_gleich"]) / len(rows),
        "jaccard_mittel_paarweise": sum(pair_j) / len(pair_j) if pair_j else None, "ursache": None, "top": tops,
    }  # fmt: skip
    res["metriken"] = metrics(res)
    return res


def metrics(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cause = res.get("ursache")
    suffix = "" if res["art"] == "frisch" else "_gespeichert"
    return {
        f"jaccard_top5_mittel{suffix}": {"wert": res["jaccard_mittel_paarweise"], "stichprobe": res["laeufe"], "ursache": cause if res["jaccard_mittel_paarweise"] is None else None},
        f"rang1_gleich_anteil{suffix}": {"wert": res["rang1_gleich_anteil"], "stichprobe": res["laeufe"], "ursache": cause},
        f"repro_bestanden_anteil{suffix}": {"wert": res["bestanden_anteil"], "stichprobe": res["laeufe"], "ursache": cause},
    }  # fmt: skip


def format_report(res: dict[str, Any]) -> str:
    if res.get("ursache"):
        return f"Reproduzierbarkeit ({res['art']}): nicht messbar: {res['ursache']}"
    lines = [f"Reproduzierbarkeit ({res['art']}), {res['laeufe']} Läufe, Bezug Lauf 1, Regel: {res['regel']}"]
    for r in res["vergleiche"]:
        jac = "nicht messbar: beide leer" if r["jaccard"] is None else f"{r['jaccard']:.2f}"
        lines.append(f"  Lauf {r['lauf']}: Jaccard {jac}, Rang 1 gleich {'ja' if r['rang1_gleich'] else 'nein'}, "
                     f"identisch {'ja' if r['identisch'] else 'nein'}, bestanden {'ja' if r['bestanden'] else 'nein'}")  # fmt: skip
    jm = res["jaccard_mittel_paarweise"]
    lines.append(f"Bestanden: {res['bestanden']} von {len(res['vergleiche'])}; Jaccard paarweise im Mittel {'nicht messbar' if jm is None else f'{jm:.2f}'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Jaccard der Top-5 und Rang-1-Gleichheit über mehrere Läufe.")
    ap.add_argument("berichte", nargs="+", help="DetectReport-JSON je Lauf, der erste ist der Bezug")
    ap.add_argument("--art", choices=KINDS, default="frisch", help="frisch (Cache umgangen) oder gespeichert (Cache-Treffer)")
    ap.add_argument("--runden", type=float, default=DEFAULT_ROUND_S, help="Rundung der Spannen in Sekunden")
    ap.add_argument("--iou", type=float, default=None, help="statt Gleichheit: Spannen ab dieser IoU gelten als gleich")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.berichte]
    res = evaluate(reports, args.art, args.runden, args.iou)
    print(format_report(res))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
