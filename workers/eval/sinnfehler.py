"""Bestätigte kritische Sinnfehler je Clip: Bogen erzeugen und auswerten (Launch-Auftrag Abschnitt 1, Review 2C).

    .venv/bin/python -m eval.sinnfehler --bogen-aus clips.json --out sinnfehler_bogen.json
    .venv/bin/python -m eval.sinnfehler --auswerten sinnfehler_bogen.json [--json sinnfehler.json]

``clips.json`` ist eine Liste ``[{"clip_id", "quelle", "text"}]``. Prüfende lesen jeden Clip gegen den vollen
Kontext der Quelle und tragen je Clip ein: ``geprueft`` (true, wenn gegen den Vollkontext geprüft) und je
gefundenem Fehler ``{"kategorie", "bestaetigt", "beschreibung"}``. Kategorien: attribution (falsche Zuordnung),
negation (Verneinung verloren oder verkehrt), certainty (Sicherheit verändert), condition (Bedingung fehlt),
number (Zahl falsch oder ohne Bezug), time (Zeitbezug falsch), context (fehlender Kontext verkehrt den Sinn).

Auswertung: Zahl der Clips mit mindestens einem bestätigten kritischen Fehler, Stichprobe (geprüfte Clips),
beobachteter Anteil, einseitige obere 95-%-Grenze nach Clopper-Pearson und Verteilung je Quelle. 0 von 20
ergibt rund 13,9 %, 1 von 20 rund 21,6 %. Die Grenze setzt unabhängige Clips voraus; Clips aus wenigen Quellen
erfüllen das nur eingeschränkt, deshalb steht die Verteilung je Quelle daneben. Ein bestätigter Fehler sperrt
den betroffenen Clip unabhängig von der Quote.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SHEET = "sinnfehler_v1"
CATEGORIES = ("attribution", "negation", "certainty", "condition", "number", "time", "context")
CONFIDENCE = 0.95
MIN_CLIPS = 20
MIN_SOURCES = 3


def binom_cdf(x: int, n: int, p: float) -> float:
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(x + 1))


def clopper_pearson_upper(x: int, n: int, confidence: float = CONFIDENCE) -> float | None:
    """Einseitige obere Grenze: das p, bei dem P(X <= x) = 1 - confidence. ``None`` ohne Stichprobe."""
    if n <= 0:
        return None
    if x >= n:
        return 1.0
    alpha = 1 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if binom_cdf(x, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def make_sheet(clips: list[dict[str, Any]], checker: str | None = None) -> dict[str, Any]:
    return {
        "bogen": SHEET,
        "pruefer": checker,
        "kategorien": list(CATEGORIES),
        "hinweis": "Je Clip gegen den vollen Kontext der Quelle prüfen; geprueft auf true setzen. Je kritischem Sinnfehler "
                   "einen Eintrag mit kategorie, bestaetigt (true nach Gegenprüfung) und beschreibung anlegen.",
        "clips": [{"clip_id": str(c["clip_id"]), "quelle": str(c["quelle"]), "text": c.get("text", ""), "geprueft": False, "kritische_sinnfehler": []} for c in clips],
    }  # fmt: skip


def validate_sheet(doc: Any) -> list[dict[str, Any]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("clips"), list):
        raise SystemExit("Sinnfehler-Bogen: Feld clips fehlt.")
    seen: set[str] = set()
    for i, c in enumerate(doc["clips"]):
        where = f"clips[{i}]"
        if not isinstance(c, dict) or not c.get("clip_id") or not c.get("quelle"):
            raise SystemExit(f"Sinnfehler-Bogen {where}: clip_id und quelle sind Pflicht.")
        if c["clip_id"] in seen:
            raise SystemExit(f"Sinnfehler-Bogen {where}: clip_id {c['clip_id']!r} steht doppelt.")
        seen.add(c["clip_id"])
        if not isinstance(c.get("geprueft"), bool):
            raise SystemExit(f"Sinnfehler-Bogen {where} ({c['clip_id']}): geprueft muss true oder false sein.")
        for j, f in enumerate(c.get("kritische_sinnfehler") or []):
            if not isinstance(f, dict) or f.get("kategorie") not in CATEGORIES:
                raise SystemExit(f"Sinnfehler-Bogen {where}.kritische_sinnfehler[{j}]: kategorie muss eine von {', '.join(CATEGORIES)} sein.")
            if not isinstance(f.get("bestaetigt"), bool):
                raise SystemExit(f"Sinnfehler-Bogen {where}.kritische_sinnfehler[{j}]: bestaetigt muss true oder false sein.")
        if c.get("kritische_sinnfehler") and not c["geprueft"]:
            raise SystemExit(f"Sinnfehler-Bogen {where} ({c['clip_id']}): Fehler eingetragen, aber geprueft ist false.")
    return doc["clips"]


def evaluate(doc: dict[str, Any]) -> dict[str, Any]:
    clips = validate_sheet(doc)
    checked = [c for c in clips if c["geprueft"]]
    with_error = [c for c in checked if any(f["bestaetigt"] for f in c.get("kritische_sinnfehler") or [])]
    unconfirmed = sum(1 for c in checked for f in c.get("kritische_sinnfehler") or [] if not f["bestaetigt"])
    per_source: dict[str, dict[str, int]] = defaultdict(lambda: {"geprueft": 0, "mit_fehler": 0})
    for c in checked:
        per_source[c["quelle"]]["geprueft"] += 1
        per_source[c["quelle"]]["mit_fehler"] += int(c in with_error)
    cats = Counter(f["kategorie"] for c in checked for f in c.get("kritische_sinnfehler") or [] if f["bestaetigt"])
    n, x = len(checked), len(with_error)
    warnings = []
    if n < MIN_CLIPS:
        warnings.append(f"Stichprobe {n} Clips liegt unter dem Minimum von {MIN_CLIPS}.")
    if len(per_source) < MIN_SOURCES:
        warnings.append(f"{len(per_source)} Quellen liegen unter dem Minimum von {MIN_SOURCES}.")
    res = {
        "clips_im_bogen": len(clips), "stichprobe": n, "mit_bestaetigtem_fehler": x,
        "beobachtet_anteil": x / n if n else None, "obere_grenze_95": clopper_pearson_upper(x, n),
        "unbestaetigte_hinweise": unconfirmed, "je_kategorie": {k: cats.get(k, 0) for k in CATEGORIES},
        "je_quelle": dict(sorted(per_source.items())), "gesperrte_clips": [c["clip_id"] for c in with_error],
        "warnungen": warnings, "ursache": None if n else "kein geprüfter Clip",
    }  # fmt: skip
    res["metriken"] = {
        "sinnfehler_obere_grenze": {"wert": res["obere_grenze_95"], "stichprobe": n, "ursache": res["ursache"]},
        "sinnfehler_beobachtet": {"wert": res["beobachtet_anteil"], "stichprobe": n, "ursache": res["ursache"]},
    }
    return res


def _pct(v: float | None) -> str:
    return "nicht messbar: kein geprüfter Clip" if v is None else f"{v * 100:.1f} %".replace(".", ",")


def format_report(res: dict[str, Any]) -> str:
    lines = [
        f"Kritische Sinnfehler: {res['mit_bestaetigtem_fehler']} von {res['stichprobe']} geprüften Clips (beobachtet {_pct(res['beobachtet_anteil'])})",
        f"Obere 95-%-Grenze (einseitig, Clopper-Pearson): {_pct(res['obere_grenze_95'])}",
        "Die Grenze setzt unabhängige Clips voraus; Clips derselben Quelle sind das nur eingeschränkt.",
        "Je Quelle: " + (", ".join(f"{q} {v['mit_fehler']} von {v['geprueft']}" for q, v in res["je_quelle"].items()) or "keine"),
        "Je Kategorie: " + ", ".join(f"{k} {v}" for k, v in res["je_kategorie"].items()),
    ]
    if res["gesperrte_clips"]:
        lines.append("Gesperrt (bestätigter kritischer Sinnfehler): " + ", ".join(res["gesperrte_clips"]))
    lines += [f"Warnung: {w}" for w in res["warnungen"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Bogen und Auswertung kritischer Sinnfehler.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bogen-aus", help="Liste der Clips (clip_id, quelle, text) als JSON")
    mode.add_argument("--auswerten", help="ausgefüllter Sinnfehler-Bogen")
    ap.add_argument("--out", help="Ziel für den leeren Bogen")
    ap.add_argument("--pruefer", help="Kennung der prüfenden Person")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args(argv)
    if args.bogen_aus:
        if not args.out:
            raise SystemExit("--bogen-aus braucht --out.")
        clips = json.loads(Path(args.bogen_aus).read_text(encoding="utf-8"))
        Path(args.out).write_text(json.dumps(make_sheet(clips, args.pruefer), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Bogen geschrieben: {args.out}")
        return
    res = evaluate(json.loads(Path(args.auswerten).read_text(encoding="utf-8")))
    print(format_report(res))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
