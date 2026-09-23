"""Einen Beispielclip im Quelltranskript wiederfinden und zeigen, was der Cutter weggelassen hat.

    .venv/bin/python -m eval.locate_in_transcript --clips /tmp/chopstr-beispiele \
        --transkripte /tmp/tr_TranskriptBP.txt /tmp/tr_TranskriptvsLinke.txt

Die interessante Frage an einem fertigen Clip ist nicht, was drin ist, sondern was direkt davor und
direkt danach im Gespräch stand und trotzdem nicht mitgenommen wurde. Genau darin steckt die
Entscheidung des Cutters.

Die Clips sind maschinell transkribiert, die Quelltranskripte von Hand geschrieben. Die Wortlaute
weichen deshalb ab (Zahlen, Eigennamen, Füllwörter). Die Zuordnung läuft über die längsten
gemeinsamen Wortfolgen, nicht über exakte Gleichheit, und meldet ihre Güte mit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

WORT = re.compile(r"[0-9a-zäöüß]+")


def tokens(text: str) -> list[str]:
    return WORT.findall(text.lower().replace("ß", "ss"))


def finde(clip: list[str], quelle: list[str]) -> dict[str, Any] | None:
    """Beste Deckung des Clips in der Quelle. Gibt Start, Ende und Anteil gemeinsamer Wörter."""
    if not clip or not quelle:
        return None
    sm = SequenceMatcher(None, quelle, clip, autojunk=False)
    bloecke = [b for b in sm.get_matching_blocks() if b.size >= 3]
    if not bloecke:
        return None
    start = min(b.a for b in bloecke)
    ende = max(b.a + b.size for b in bloecke)
    getroffen = sum(b.size for b in bloecke)
    return {"start": start, "ende": ende, "guete": round(getroffen / len(clip), 3)}


def zeige(woerter: list[str], von: int, bis: int) -> str:
    return " ".join(woerter[max(0, von) : bis])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Beispielclips im Quelltranskript verorten.")
    ap.add_argument("--clips", required=True, help="Ordner mit den zwischengespeicherten Clip-Transkripten")
    ap.add_argument("--transkripte", required=True, nargs="+", help="Quelltranskripte als Textdateien")
    ap.add_argument("--kontext", type=int, default=45, help="Wörter davor und danach, Standard 45")
    ap.add_argument("--mindestguete", type=float, default=0.25, help="Zuordnung unter diesem Wert verwerfen")
    ap.add_argument("--nur", default=None, help="Nur Clips, deren Name das enthält")
    args = ap.parse_args(argv)

    quellen = []
    for p in args.transkripte:
        roh = Path(p).read_text(encoding="utf-8")
        quellen.append({"name": Path(p).stem, "woerter": tokens(roh)})

    dateien = sorted(Path(args.clips).glob("*.json"))
    if args.nur:
        dateien = [p for p in dateien if args.nur.lower() in p.name.lower()]

    for p in dateien:
        daten = json.loads(p.read_text(encoding="utf-8"))
        clip = tokens(daten.get("text", ""))
        if not clip:
            continue
        bester, beste = None, None
        for q in quellen:
            t = finde(clip, q["woerter"])
            if t and (beste is None or t["guete"] > beste["guete"]):
                bester, beste = q, t
        print("=" * 100)
        gruppe = "POSITIV" if p.name.startswith("Positive") else "NEGATIV"
        print(f"{gruppe}  {daten.get('datei')}   ({len(clip)} Wörter)")
        if beste is None or beste["guete"] < args.mindestguete:
            g = f"{beste['guete']:.2f}" if beste else "keine"
            print(f"  Nicht sicher zuzuordnen (beste Güte {g}). Stammt vermutlich aus einem anderen Gespräch.")
            print()
            continue
        w = bester["woerter"]
        print(f"  Quelle: {bester['name']}, Wörter {beste['start']} bis {beste['ende']}, Güte {beste['guete']:.2f}")
        print()
        print("  DAVOR weggelassen:")
        print(f"    ...{zeige(w, beste['start'] - args.kontext, beste['start'])}")
        print()
        print("  IM CLIP, Anfang:")
        print(f"    {zeige(w, beste['start'], beste['start'] + 25)}...")
        print("  IM CLIP, Ende:")
        print(f"    ...{zeige(w, beste['ende'] - 25, beste['ende'])}")
        print()
        print("  DANACH weggelassen:")
        print(f"    {zeige(w, beste['ende'], beste['ende'] + args.kontext)}...")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
