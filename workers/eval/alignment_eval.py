"""Highlight-Versatz: Wortanfang und Wortende des Transkripts gegen manuell kontrollierte Audioanker.

    .venv/bin/python -m eval.alignment_eval --anker eval/data/audioanker/<quelle>.json \
        --transkript transkript.json [--fenster 1.0] [--json versatz.json]

Je Anker wird das Transkriptwort mit gleichem normalisiertem Text gesucht, dessen Anfang dem Anker am nächsten
liegt (höchstens ``--fenster`` Sekunden entfernt, jedes Wort nur einmal). Versatz in Millisekunden als Betrag:
Median und 95. Perzentil (nächster Rang), dazu der Median mit Vorzeichen (positiv heißt: Transkript zu spät).
Fehlende Alignments (Wort nicht gefunden oder ohne Zeit) werden getrennt gezählt und nicht als 0 ms gewertet.
Alles gesamt und je Kategorie (name, betrag, prozent, verneinung, einschraenkung, sonstiges).

Nie gegen Whisper selbst messen: Referenz sind die Audioanker (Review 4C).
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval import data_loader, wer_eval

DEFAULT_WINDOW_S = 1.0


def _norm(text: str) -> str:
    return " ".join(wer_eval.normalize(str(text), ch=True))


def percentile(values: list[float], q: float) -> float | None:
    """Perzentil nach dem nächsten Rang (``q`` zwischen 0 und 100); leere Liste ergibt ``None``."""
    if not values:
        return None
    s = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(s)))
    return s[rank - 1]


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def match_anchors(anchors: list[dict], words: list[dict], window_s: float = DEFAULT_WINDOW_S) -> list[dict[str, Any]]:
    """Je Anker das passende Transkriptwort oder ein Grund, warum keines passt."""
    by_text: dict[str, list[int]] = defaultdict(list)
    for i, w in enumerate(words):
        by_text[_norm(w.get("text", w.get("wort", "")))].append(i)
    used: set[int] = set()
    out = []
    for a in anchors:
        ref_t = a["anker_start"] if a.get("anker_start") is not None else a["anker_ende"]
        cands = [i for i in by_text.get(_norm(a["wort"]), []) if i not in used]
        best, best_d, timeless = None, None, False
        for i in cands:
            w = words[i]
            t = w.get("start") if a.get("anker_start") is not None else w.get("end")
            if t is None:
                timeless = True
                continue
            d = abs(float(t) - ref_t)
            if d <= window_s and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is None:
            out.append({**a, "status": "ohne_zeit" if timeless else "nicht_gefunden"})
            continue
        used.add(best)
        w = words[best]
        row: dict[str, Any] = {**a, "status": "ok", "wort_index": best}
        if a.get("anker_start") is not None and w.get("start") is not None:
            row["versatz_anfang_ms"] = round((float(w["start"]) - a["anker_start"]) * 1000, 1)
        if a.get("anker_ende") is not None and w.get("end") is not None:
            row["versatz_ende_ms"] = round((float(w["end"]) - a["anker_ende"]) * 1000, 1)
        out.append(row)
    return out


def summarize(rows: list[dict]) -> dict[str, Any]:
    starts = [r["versatz_anfang_ms"] for r in rows if "versatz_anfang_ms" in r]
    ends = [r["versatz_ende_ms"] for r in rows if "versatz_ende_ms" in r]
    missing = [r for r in rows if r["status"] != "ok"]
    out: dict[str, Any] = {"anker": len(rows), "fehlend": len(missing), "fehlend_anteil": len(missing) / len(rows) if rows else None,
                           "fehlend_je_grund": {k: sum(1 for r in missing if r["status"] == k) for k in ("nicht_gefunden", "ohne_zeit")}}  # fmt: skip
    for name, vals in (("anfang", starts), ("ende", ends)):
        abs_vals = [abs(v) for v in vals]
        out[name] = {"n": len(vals), "median_ms": median(abs_vals), "p95_ms": percentile(abs_vals, 95), "median_mit_vorzeichen_ms": median(vals),
                     "ursache": None if vals else ("keine Anker" if not rows else "kein Wort mit Zeit gefunden")}  # fmt: skip
    return out


def evaluate(anchors: list[dict], words: list[dict], window_s: float = DEFAULT_WINDOW_S) -> dict[str, Any]:
    rows = match_anchors(anchors, words, window_s)
    per_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        per_cat[r.get("kategorie", "sonstiges")].append(r)
    res = {"gesamt": summarize(rows), "je_kategorie": {c: summarize(rs) for c, rs in sorted(per_cat.items())}, "zeilen": rows, "fenster_s": window_s}
    res["metriken"] = metrics(res)
    return res


def metrics(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    g = res["gesamt"]
    out = {}
    for side, label in (("anfang", "anfang"), ("ende", "ende")):
        block = g[side]
        for stat in ("median", "p95"):
            out[f"versatz_{label}_{stat}_ms"] = {"wert": block[f"{stat}_ms"], "stichprobe": block["n"], "ursache": block["ursache"]}
    out["alignment_fehlend_anteil"] = {"wert": g["fehlend_anteil"], "stichprobe": g["anker"], "ursache": None if g["anker"] else "keine Anker"}
    return out


def anchors_from_speaker_changes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Synthetische Anker aus ``sprecherwechsel.json`` (Testmaterial): Satzanfang als Anfang des ersten Wortes,
    Satzende als Ende des letzten Wortes, Kategorie ``sonstiges``. Das ist Montage-Wahrheit aus Sprachsynthese,
    kein manuell kontrollierter Anker; Stille am Dateianfang der Synthese ist nicht herausgerechnet."""
    out = []
    for sent in doc.get("saetze") or []:
        toks = [t for t in str(sent["text"]).split() if _norm(t)]
        if not toks:
            continue
        if len(toks) == 1:
            out.append({"wort": toks[0], "anker_start": float(sent["start"]), "anker_ende": float(sent["end"]), "kategorie": "sonstiges"})
            continue
        out.append({"wort": toks[0], "anker_start": float(sent["start"]), "anker_ende": None, "kategorie": "sonstiges"})
        out.append({"wort": toks[-1], "anker_start": None, "anker_ende": float(sent["end"]), "kategorie": "sonstiges"})
    return out


def _ms(value: float | None, cause: str | None) -> str:
    return f"nicht messbar: {cause}" if value is None else f"{value:.0f} ms"


def format_report(res: dict[str, Any]) -> str:
    lines = []
    for title, block in (("gesamt", res["gesamt"]), *res["je_kategorie"].items()):
        a, e = block["anfang"], block["ende"]
        lines.append(f"{title}: {block['anker']} Anker, fehlend {block['fehlend']}; Anfang Median {_ms(a['median_ms'], a['ursache'])}, "
                     f"P95 {_ms(a['p95_ms'], a['ursache'])}; Ende Median {_ms(e['median_ms'], e['ursache'])}, P95 {_ms(e['p95_ms'], e['ursache'])}")  # fmt: skip
    return "\n".join(lines)


def _words(path: str | Path) -> list[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return doc if isinstance(doc, list) else (doc.get("words") or doc.get("woerter") or [])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Highlight-Versatz gegen Audioanker.")
    ap.add_argument("--anker", required=True, help="audioanker/<quelle>.json oder sprecherwechsel.json (synthetisch)")
    ap.add_argument("--transkript", required=True, help="Transkript-JSON mit text, start, end je Wort")
    ap.add_argument("--fenster", type=float, default=DEFAULT_WINDOW_S, help="größter Abstand für die Zuordnung in Sekunden")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    doc = json.loads(Path(args.anker).read_text(encoding="utf-8"))
    try:
        anchors = anchors_from_speaker_changes(doc) if "saetze" in doc else data_loader.validate_anchors(doc, args.anker)["anker"]
    except data_loader.DataError as exc:
        raise SystemExit(f"Fehler: {exc}") from exc
    res = evaluate(anchors, _words(args.transkript), args.fenster)
    print(format_report(res))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
