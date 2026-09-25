"""Der Referenzsatz: welche Beispiele gemessen wurden, und wie sie hiessen.

    .venv/bin/python -m eval.referenzsatz erfassen \\
        --positiv "/pfad/Positive Beispiele" --negativ "/pfad/Negative Beispiele" \\
        --messung messung.json --out eval/clips/referenzsatz_v1.json

    .venv/bin/python -m eval.referenzsatz pruefen \\
        --positiv "/pfad/Positive Beispiele" --negativ "/pfad/Negative Beispiele"

WOZU. ``eval/learn_from_examples.py`` misst Beispielclips und wirft eine Tabelle aus. Zwei Laeufe
gegeneinander zu halten geht damit nicht: niemand weiss hinterher, ob dieselben Dateien drin waren.
Eine Zahl, die sich geaendert hat, kann dann alles heissen - die Pipeline ist besser geworden, oder
es lagen drei Dateien mehr im Ordner.

Diese Datei haelt deshalb den Satz fest, mit dem gemessen wurde: je Datei ihr SHA-256 und ihre
Groesse. Damit laesst sich ein spaeterer Lauf pruefen, bevor die Zahlen verglichen werden.

WAS NICHT HINEINKOMMT. Die Videos selbst und ihr Text bleiben draussen. Es sind Aufnahmen von
Kunden; sie gehoeren nicht in ein Repository. Im Manifest stehen Pruefsummen und Zahlen, sonst
nichts. Wer die Messung nachvollziehen will, braucht die Dateien selbst, und die bekommt er von
dem, dem sie gehoeren.

EHRLICH ZUR AUSSAGEKRAFT. Ein Satz aus wenigen Clips traegt keine Aussage darueber, was einen guten
Clip ausmacht. Das Manifest schreibt die Zahl der Beispiele mit, damit sie in jeder Auswertung
dabeisteht.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
VERSION = "referenzsatz_v1"

# Ein Satz unter dieser Groesse ist eine Stichprobe und keine Grundlage. Die Zahl steht hier, damit
# jede Auswertung sie mitschreiben kann statt sie zu verschweigen.
MINDESTGROESSE_JE_GRUPPE = 20


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dateien(ordner: Path) -> list[Path]:
    return sorted(p for p in ordner.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES)


def erfassen(ordner: Path, label: str) -> list[dict[str, Any]]:
    aus = []
    for p in dateien(ordner):
        aus.append({"datei": p.name, "label": label, "bytes": p.stat().st_size, "sha256": sha256(p)})
    return aus


def kennzahlen(messung: dict[str, Any]) -> dict[str, Any]:
    """Nur die zusammengefassten Zahlen aus einem Lauf von ``learn_from_examples``.

    Die Einzelmessungen enthalten Textausschnitte aus den Aufnahmen. Die bleiben draussen."""
    aus: dict[str, Any] = {}
    for gruppe in ("positiv", "negativ"):
        teil = messung.get(gruppe) or {}
        aus[gruppe] = {k: v for k, v in (teil.get("summe") or {}).items()}
    return aus


def schreiben(out: Path, eintraege: list[dict[str, Any]], zahlen: dict[str, Any]) -> dict[str, Any]:
    pos = sum(1 for e in eintraege if e["label"] == "positiv")
    neg = len(eintraege) - pos
    doc = {
        "version": VERSION,
        "erfasst_am": datetime.now(UTC).date().isoformat(),
        "anzahl": {"positiv": pos, "negativ": neg},
        "belastbar": pos >= MINDESTGROESSE_JE_GRUPPE and neg >= MINDESTGROESSE_JE_GRUPPE,
        "mindestgroesse_je_gruppe": MINDESTGROESSE_JE_GRUPPE,
        "dateien": eintraege,
        "kennzahlen": zahlen,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def pruefen(manifest: Path, ordner: dict[str, Path]) -> tuple[list[str], list[str]]:
    """Stimmt der Satz auf der Platte noch mit dem Manifest ueberein?

    Gibt zwei Listen zurueck: was fehlt, und was sich geaendert hat."""
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    fehlt: list[str] = []
    anders: list[str] = []
    for e in doc["dateien"]:
        p = ordner[e["label"]] / e["datei"]
        if not p.is_file():
            fehlt.append(f"{e['label']}/{e['datei']}")
            continue
        if p.stat().st_size != e["bytes"] or sha256(p) != e["sha256"]:
            anders.append(f"{e['label']}/{e['datei']}")
    return fehlt, anders


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("befehl", choices=["erfassen", "pruefen"])
    ap.add_argument("--positiv", type=Path, required=True)
    ap.add_argument("--negativ", type=Path, required=True)
    ap.add_argument("--messung", type=Path, help="JSON aus eval.learn_from_examples (nur beim Erfassen)")
    ap.add_argument("--out", type=Path, default=Path("eval/clips/referenzsatz_v1.json"))
    a = ap.parse_args(argv)

    ordner = {"positiv": a.positiv, "negativ": a.negativ}
    for label, p in ordner.items():
        if not p.is_dir():
            print(f"Ordner fehlt: {label} = {p}", file=sys.stderr)
            return 2

    if a.befehl == "erfassen":
        eintraege = erfassen(a.positiv, "positiv") + erfassen(a.negativ, "negativ")
        zahlen = kennzahlen(json.loads(a.messung.read_text(encoding="utf-8"))) if a.messung else {}
        doc = schreiben(a.out, eintraege, zahlen)
        print(f"{doc['anzahl']['positiv']} positiv, {doc['anzahl']['negativ']} negativ -> {a.out}")
        if not doc["belastbar"]:
            print(
                f"Achtung: unter {MINDESTGROESSE_JE_GRUPPE} Beispielen je Gruppe. Die Zahlen beschreiben"
                " diesen Satz und sonst nichts.",
                file=sys.stderr,
            )
        return 0

    fehlt, anders = pruefen(a.out, ordner)
    if not fehlt and not anders:
        print("Der Satz stimmt mit dem Manifest ueberein.")
        return 0
    for f in fehlt:
        print(f"fehlt:  {f}")
    for f in anders:
        print(f"anders: {f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
