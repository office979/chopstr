"""Die Auswahlliste und der Schriftordner müssen zusammenpassen.

Bis hierher lagen die Schriftdateien bewusst nicht im Repository, und die Oberfläche bot Schriften
an, für die es keine Datei gab: der Nutzer stellte etwas ein, die Vorschau zeigte eine Ersatzschrift
und der Renderer brannte Inter ein. Seit die Dateien mitgeliefert werden, hält dieser Test die
beiden Seiten zusammen - eine neue Zeile in der Liste ohne Datei fällt sofort auf.
"""

from __future__ import annotations

import json
from pathlib import Path

from chopstr_worker.pipeline import captions_de, render

WURZEL = Path(__file__).resolve().parents[2]
LISTE = json.loads((WURZEL / "packages" / "design" / "caption_fonts.json").read_text(encoding="utf-8"))
ORDNER = WURZEL / "workers" / "fonts"


def test_zu_jeder_schrift_der_liste_liegt_eine_datei():
    fehlend = [s["datei"] for s in LISTE["schriften"] if not (ORDNER / s["datei"]).is_file()]
    assert fehlend == [], f"Dateien fehlen in workers/fonts: {fehlend}"


def test_der_renderer_findet_jede_schrift():
    # Derselbe Weg wie im Renderlauf: Name aus der Liste, Datei ueber captions_de, Ordner ueber render.
    ordner = render.default_fonts_dir()
    for s in LISTE["schriften"]:
        datei = captions_de.schrift_datei(s["id"])
        assert datei, f"{s['id']} hat keinen Dateinamen"
        assert (ordner / datei).is_file(), f"{s['id']}: {datei} fehlt in {ordner}"


def test_zu_jeder_schrift_liegt_ein_lizenztext():
    """Die OFL verlangt, dass Lizenztext und Urhebervermerk mitgeliefert werden.

    Eine Schriftdatei ohne ihren Lizenztext weiterzugeben verletzt sie. Inter bringt seinen Vermerk
    in der README mit, die uebrigen acht liegen als Datei daneben."""
    lizenzen = list((ORDNER / "lizenzen").glob("*-OFL.txt"))
    assert len(lizenzen) >= len(LISTE["schriften"]) - 1
    for datei in lizenzen:
        text = datei.read_text(encoding="utf-8")
        assert "SIL Open Font License" in text
        assert "Copyright" in text


def test_die_geschnittenen_fassungen_sind_wirklich_fett():
    """Google liefert vier dieser Schriften nur als variable Datei; daraus wird eine feste Fassung
    bei Strichstaerke 700 geschnitten. Waere der Schnitt misslungen, stuende im Bild die
    Normalstaerke - und niemand haette es gemerkt."""
    from fontTools.ttLib import TTFont

    for datei in ("Montserrat-Bold.ttf", "Oswald-Bold.ttf", "PlayfairDisplay-Bold.ttf", "SpaceGrotesk-Bold.ttf"):
        f = TTFont(ORDNER / datei)
        assert "fvar" not in f, f"{datei} ist noch variabel"
        assert f["OS/2"].usWeightClass == 700, f"{datei} hat Strichstaerke {f['OS/2'].usWeightClass}"
        f.close()
