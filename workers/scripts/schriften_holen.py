"""Die Untertitel-Schriften beschaffen, damit sie im Repository liegen.

    .venv/bin/python -m scripts.schriften_holen          # fehlende holen
    .venv/bin/python -m scripts.schriften_holen --alle   # alle neu holen

WARUM DAS SKRIPT EXISTIERT, OBWOHL DIE DATEIEN EINGECHECKT SIND: es ist der Nachweis, woher jede
Datei kommt. Bei Schriften ist das keine Formsache. Die SIL Open Font License verlangt, dass
Lizenztext und Urhebervermerk mitgeliefert werden; wer eine Schriftdatei ohne diese Angabe
weitergibt, verletzt sie. Das Skript holt beides zusammen und legt den Lizenztext neben die Datei.

WARUM MANCHE SCHRIFTEN GESCHNITTEN WERDEN: Montserrat, Oswald, Playfair Display und Space Grotesk
liegen bei Google nur noch als variable Schrift vor, also als eine Datei mit einer stufenlosen
Strichstaerke. libass und ffmpeg nehmen daraus die Voreinstellung, und die ist Normalstaerke. Wer
in chopstr „Montserrat" waehlt, bekaeme also duenne Untertitel, ohne dass es jemand merkt - genau
die Art von stillem Unterschied, die dieses Produkt nicht haben will. Deshalb wird aus der
variablen Datei eine feste Fassung bei Strichstaerke 700 erzeugt.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROH = "https://raw.githubusercontent.com/google/fonts/main/ofl"
HIER = Path(__file__).resolve().parents[1]
ZIEL = HIER / "fonts"
LIZENZEN = ZIEL / "lizenzen"

# ordner bei google/fonts, Quelldatei, Zieldatei, Strichstaerke fuer den Schnitt (None = direkt)
SCHRIFTEN: list[tuple[str, str, str, int | None]] = [
    ("anton", "Anton-Regular.ttf", "Anton-Regular.ttf", None),
    ("bebasneue", "BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf", None),
    ("archivoblack", "ArchivoBlack-Regular.ttf", "ArchivoBlack-Regular.ttf", None),
    ("poppins", "Poppins-Bold.ttf", "Poppins-Bold.ttf", None),
    ("montserrat", "Montserrat[wght].ttf", "Montserrat-Bold.ttf", 700),
    ("oswald", "Oswald[wght].ttf", "Oswald-Bold.ttf", 700),
    ("playfairdisplay", "PlayfairDisplay[wght].ttf", "PlayfairDisplay-Bold.ttf", 700),
    ("spacegrotesk", "SpaceGrotesk[wght].ttf", "SpaceGrotesk-Bold.ttf", 700),
]


def laden(url: str, ziel: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 - feste, bekannte Adresse
        ziel.write_bytes(r.read())


def schneiden(quelle: Path, ziel: Path, gewicht: int) -> None:
    """Aus einer variablen Schrift eine feste Fassung bei ``gewicht`` erzeugen.

    ``updateFontNames`` setzt Familien- und Schnittnamen richtig, damit libass die Datei unter dem
    Familiennamen findet und sie als Bold erkennt statt kuenstlich fett zu rechnen."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    f = TTFont(quelle)
    instancer.instantiateVariableFont(f, {"wght": gewicht}, inplace=True, updateFontNames=True)
    f.save(ziel)
    f.close()


def namen(pfad: Path) -> tuple[str, str]:
    from fontTools.ttLib import TTFont

    f = TTFont(pfad)
    tab = f["name"]
    familie = tab.getDebugName(16) or tab.getDebugName(1) or "?"
    schnitt = tab.getDebugName(17) or tab.getDebugName(2) or "?"
    f.close()
    return familie, schnitt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alle", action="store_true", help="auch vorhandene Dateien neu holen")
    a = ap.parse_args(argv)

    ZIEL.mkdir(parents=True, exist_ok=True)
    LIZENZEN.mkdir(parents=True, exist_ok=True)
    tmp = ZIEL / ".tmp"
    tmp.mkdir(exist_ok=True)
    fehler = 0
    try:
        for ordner, quelldatei, zieldatei, gewicht in SCHRIFTEN:
            ziel = ZIEL / zieldatei
            if ziel.is_file() and not a.alle:
                print(f"  = {zieldatei} liegt schon da")
                continue
            roh = tmp / quelldatei
            try:
                laden(f"{ROH}/{ordner}/{quelldatei.replace('[', '%5B').replace(']', '%5D')}", roh)
                laden(f"{ROH}/{ordner}/OFL.txt", LIZENZEN / f"{ordner}-OFL.txt")
            except OSError as e:
                print(f"  ! {zieldatei}: {e}", file=sys.stderr)
                fehler += 1
                continue
            if gewicht is None:
                shutil.copyfile(roh, ziel)
            else:
                schneiden(roh, ziel, gewicht)
            familie, schnitt = namen(ziel)
            print(f"  + {zieldatei}  ({familie} / {schnitt}, {ziel.stat().st_size // 1024} KB)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Gegenprobe gegen die gemeinsame Liste: was dort steht, muss hier liegen.
    liste = json.loads((HIER.parent / "packages" / "design" / "caption_fonts.json").read_text(encoding="utf-8"))
    fehlend = [s["datei"] for s in liste["schriften"] if not (ZIEL / s["datei"]).is_file()]
    if fehlend:
        print("Es fehlen noch:", ", ".join(fehlend), file=sys.stderr)
        return 1
    print(f"Alle {len(liste['schriften'])} Schriften aus caption_fonts.json liegen in {ZIEL}.")
    return 1 if fehler else 0


if __name__ == "__main__":
    raise SystemExit(main())
