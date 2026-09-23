"""Text aus einem PDF holen, ohne zusätzliche Abhängigkeit.

    .venv/bin/python -m eval.pdf_text datei.pdf > datei.txt

Gedacht für die Transkripte, die als PDF geliefert werden. Bewusst kein vollständiger PDF-Leser,
sondern genau so viel, wie diese Dateien brauchen: Inhaltsströme entpacken, Textoperatoren lesen,
Glyph-Nummern über die ToUnicode-Tabelle der eingebetteten Schrift in Zeichen zurückübersetzen.

Warum nicht einfach eine Bibliothek: Auf dieser Maschine ist keine installiert, und für drei
Transkripte lohnt keine neue Abhängigkeit im Projekt. Wenn hier später mehr gebraucht wird, ist
pypdf der richtige Schritt, nicht dieses Modul.

Grenzen, ehrlich benannt: Es werden nur unkomprimierte und mit Flate komprimierte Ströme gelesen,
keine verschlüsselten PDFs, keine gescannten Seiten ohne Textebene. Die Lesereihenfolge folgt der
Reihenfolge im Inhaltsstrom, nicht der optischen Anordnung; bei mehrspaltigem Satz kann sie
durcheinandergeraten. Für fortlaufende Transkripte stimmt sie.
"""

from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path

STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
HEXPAAR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
HEXTRIPEL = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
# Textoperatoren: einzelne Zeichenkette (Tj) und Array mit Kerning (TJ)
TJ_EINZEL = re.compile(rb"<([0-9A-Fa-f]+)>\s*Tj")
TJ_ARRAY = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
TJ_TEIL = re.compile(rb"<([0-9A-Fa-f]+)>|(-?\d+\.?\d*)")
# Achtung: nur T* und TD (grosses D) sind Zeilenwechsel. Td mit kleinem d verschiebt die
# Textposition und wird in diesen Dateien fuer JEDEN einzelnen Buchstaben benutzt. Wer Td als
# Umbruch liest, bekommt ein Dokument mit einem Zeichen pro Zeile.
ZEILENUMBRUCH = re.compile(rb"T\*|\bTD\b|\bET\b")


def entpacke(roh: bytes) -> list[bytes]:
    """Alle lesbaren Ströme, entpackt wo nötig."""
    out = []
    for s in STREAM.findall(roh):
        try:
            out.append(zlib.decompress(s))
        except zlib.error:
            out.append(s)
    return out


def utf16be(h: bytes) -> str:
    """Zielwert einer ToUnicode-Zuordnung: UTF-16BE, oft mehrere Zeichen."""
    b = bytes.fromhex(h.decode("ascii"))
    if len(b) % 2:
        b += b"\x00"
    try:
        return b.decode("utf-16-be")
    except UnicodeDecodeError:
        return ""


def tounicode(stroeme: list[bytes]) -> dict[int, str]:
    """Glyph-Nummer zu Zeichen, aus allen ToUnicode-Tabellen der Datei zusammengesetzt."""
    tabelle: dict[int, str] = {}
    for d in stroeme:
        if b"beginbfchar" not in d and b"beginbfrange" not in d:
            continue
        for block in BFCHAR.findall(d):
            for quelle, ziel in HEXPAAR.findall(block):
                tabelle[int(quelle, 16)] = utf16be(ziel)
        for block in BFRANGE.findall(d):
            for von, bis, ziel in HEXTRIPEL.findall(block):
                start, ende = int(von, 16), int(bis, 16)
                erstes = utf16be(ziel)
                if len(erstes) != 1 or ende - start > 65535:
                    continue
                for i in range(start, ende + 1):
                    tabelle[i] = chr(ord(erstes) + (i - start))
    return tabelle


def glyph_zu_zeichen(g: int, tabelle: dict[int, str]) -> str:
    """Erst die Tabelle der Datei, sonst die feste Reihenfolge der Teilschrift.

    Teilschriften nummerieren ihre Glyphen der Reihe nach, beginnend bei 3 für das Leerzeichen.
    Daraus ergibt sich für den ASCII-Bereich ein fester Versatz von 29. Das ist eine Krücke und
    greift nur, wenn die Datei keine ToUnicode-Tabelle mitliefert.
    """
    if g in tabelle:
        return tabelle[g]
    z = g + 29
    return chr(z) if 32 <= z < 127 else ""


def text(pfad: str | Path, fliesstext: bool = True) -> str:
    roh = Path(pfad).read_bytes()
    stroeme = entpacke(roh)
    tabelle = tounicode(stroeme)

    teile: list[str] = []
    for d in stroeme:
        if b"Tj" not in d and b"TJ" not in d:
            continue
        pos = 0
        for treffer in re.finditer(rb"<([0-9A-Fa-f]+)>\s*Tj|\[(.*?)\]\s*TJ|T\*|\bTD\b|\bET\b", d, re.S):
            zwischen = d[pos : treffer.start()]
            pos = treffer.end()
            if ZEILENUMBRUCH.search(zwischen):
                teile.append("\n")
            roh_einzel, roh_array = treffer.group(1), treffer.group(2)
            if roh_einzel:
                teile.append(zeichenkette(roh_einzel, tabelle))
            elif roh_array is not None:
                for hexteil, zahl in TJ_TEIL.findall(roh_array):
                    if hexteil:
                        teile.append(zeichenkette(hexteil, tabelle))
                    elif zahl and float(zahl) < -180:
                        # grosser negativer Kern-Wert heisst in der Praxis Wortabstand
                        teile.append(" ")
            else:
                teile.append("\n")

    roh_text = "".join(teile)
    if fliesstext:
        # Diese Dateien setzen jedes Wort einzeln und lösen dabei einen Zeilenwechsel aus. Die
        # Zeilenstruktur trägt also keine Bedeutung, nur die Wortfolge. Für fortlaufende
        # Transkripte ist Fließtext das brauchbare Ergebnis; bei mehrspaltigem Satz wäre es falsch.
        return re.sub(r"\s+", " ", roh_text).strip()
    roh_text = re.sub(r"[ \t]+", " ", roh_text)
    roh_text = re.sub(r"\n{3,}", "\n\n", roh_text)
    return "\n".join(z.strip() for z in roh_text.splitlines()).strip()


def zeichenkette(h: bytes, tabelle: dict[int, str]) -> str:
    s = h.decode("ascii")
    if len(s) % 4:
        s = s.ljust(len(s) + (4 - len(s) % 4), "0")
    return "".join(glyph_zu_zeichen(int(s[i : i + 4], 16), tabelle) for i in range(0, len(s), 4))


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit("Aufruf: python -m eval.pdf_text datei.pdf")
    for pfad in argv:
        sys.stdout.write(text(pfad))
        sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1:])
