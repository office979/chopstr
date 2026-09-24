"""Untertitel-Stil je Clip: Grenzen, Farben, Schriften, Zusammenlegen mit dem Markenprofil.

Der Leitsatz für dieses Modul: ein Stil darf niemals einen Render verhindern. Was nicht passt, wird
in den erlaubten Bereich gezogen oder übergangen. Deshalb prüft hier fast jeder Test, dass ein
unsinniger Wert ein brauchbares Preset ergibt statt einer Ausnahme.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chopstr_worker.activities import render as act
from chopstr_worker.pipeline import captions_de as c

WURZEL = Path(__file__).resolve().parents[2]


# -- Schriftenliste --------------------------------------------------------------------------------
def test_die_liste_liegt_ausserhalb_des_workers():
    """Oberfläche und Renderer müssen dieselbe Liste lesen, sonst bietet die eine an, was die andere
    nicht kennt."""
    p = WURZEL / "packages" / "design" / "caption_fonts.json"
    assert p.is_file(), p
    daten = json.loads(p.read_text(encoding="utf-8"))
    assert daten["ruecklauf"] in [s["id"] for s in daten["schriften"]]
    for s in daten["schriften"]:
        assert s["id"] and s["datei"] and s["beschreibung"]


def test_jede_schrift_hat_einen_eindeutigen_namen():
    namen = c.schrift_namen()
    assert len(namen) == len(set(namen))
    assert "Inter" in namen


def test_datei_zu_einer_unbekannten_schrift_gibt_es_nicht():
    assert c.schrift_datei("Comic Sans") is None
    assert c.schrift_datei("Inter")


# -- Farben ----------------------------------------------------------------------------------------
def test_hexfarbe_wird_in_die_ass_schreibweise_gedreht():
    """ASS dreht die Reihenfolge um. Falsch herum fällt nicht auf, es sieht nur falsch aus."""
    assert c.ass_farbe("#ffd700") == "&H0000D7FF"   # entspricht dem eingebauten Highlight
    assert c.ass_farbe("#FF0000") == "&H000000FF"   # Rot, nicht Blau
    assert c.ass_farbe("#0000FF") == "&H00FF0000"


def test_bereits_gesetzte_ass_werte_gehen_durch():
    assert c.ass_farbe("&H0000D7FF") == "&H0000D7FF"


@pytest.mark.parametrize("wert", ["", "   ", "#12345", "#GGGGGG", "blau", None])
def test_unbrauchbare_farben_werden_verworfen_statt_geraten(wert):
    assert c.ass_farbe(wert) is None


# -- Grenzen ---------------------------------------------------------------------------------------
def test_zu_grosse_schrift_wird_auf_das_erlaubte_gezogen():
    p = c.style_anwenden(c.preset_for("tiktok_words"), {"font_px": 9999})
    assert p.font_px == c.STIL_GRENZEN["font_px"][1]


def test_zu_kleine_schrift_ebenso():
    p = c.style_anwenden(c.preset_for("tiktok_words"), {"font_px": 2})
    assert p.font_px == c.STIL_GRENZEN["font_px"][0]


def test_ein_bis_sechs_woerter_je_einblendung():
    for n in range(1, 7):
        assert c.style_anwenden(c.preset_for("tiktok_bold"), {"words_per_card": n}).words_per_card == n
    assert c.style_anwenden(c.preset_for("tiktok_bold"), {"words_per_card": 12}).words_per_card == 6
    assert c.style_anwenden(c.preset_for("tiktok_bold"), {"words_per_card": 0}).words_per_card == 1


def test_ein_wort_bekommt_immer_nur_eine_zeile():
    """Ein Wort kann keine zweite Zeile füllen; sonst rechnet max_chars mit einer Zeile, die es nicht gibt."""
    p = c.style_anwenden(c.preset_for("tiktok_bold"), {"words_per_card": 1, "max_lines": 3})
    assert p.max_lines == 1


def test_mehrere_woerter_behalten_die_eingestellte_zeilenzahl():
    p = c.style_anwenden(c.preset_for("tiktok_bold"), {"words_per_card": 5, "max_lines": 2})
    assert (p.words_per_card, p.max_lines) == (5, 2)


@pytest.mark.parametrize("wert", ["viel", None, [], {}, True, float("nan"), float("inf")])
def test_unsinnige_zahlen_stoppen_nichts(wert):
    p = c.style_anwenden(c.preset_for("tiktok_words"), {"font_px": wert})
    assert p.font_px == c.preset_for("tiktok_words").font_px


def test_unbekannte_felder_werden_uebergangen():
    p = c.style_anwenden(c.preset_for("tiktok_words"), {"schriftart": "Anton", "zoom": 3, "name": "x"})
    assert p == c.preset_for("tiktok_words")


def test_ein_leerer_stil_aendert_nichts():
    p = c.preset_for("reels_words")
    assert c.style_anwenden(p, {}) is p
    assert c.style_anwenden(p, None) is p


# -- Schriftwahl -----------------------------------------------------------------------------------
def test_eine_schrift_aus_der_liste_wird_uebernommen():
    assert c.style_anwenden(c.preset_for("tiktok_words"), {"font": "Anton"}).font == "Anton"


def test_eine_schrift_ausserhalb_der_liste_nicht():
    assert c.style_anwenden(c.preset_for("tiktok_words"), {"font": "Comic Sans"}).font == "Inter"


# -- Umrechnung auf andere Ausgabegrößen -----------------------------------------------------------
def test_eingestellte_groessen_gelten_fuer_hochkant_und_werden_mitskaliert():
    """Die Oberfläche zeigt 1080x1920. Bei 4:5 muss dieselbe Einstellung kleiner herauskommen."""
    hoch = c.style_anwenden(c.scaled_preset("tiktok_words", 1080, 1920), {"font_px": 100}, 1920 / c.H)
    vier_fuenf = c.style_anwenden(c.scaled_preset("tiktok_words", 1080, 1350), {"font_px": 100}, 1350 / c.H)
    assert hoch.font_px == 100
    assert vier_fuenf.font_px == pytest.approx(round(100 * 1350 / 1920), abs=1)


def test_wortzahl_wird_nicht_skaliert():
    """Eine Wortzahl ist keine Länge. Sie mitzuskalieren ergäbe bei 4:5 drei statt vier Wörter."""
    p = c.style_anwenden(c.scaled_preset("tiktok_bold", 1080, 1350), {"words_per_card": 4}, 1350 / c.H)
    assert p.words_per_card == 4


# -- Zusammenlegen mit dem Markenprofil ------------------------------------------------------------
def test_der_clip_sticht_die_marke():
    zus = act.caption_style_zusammen({"font": "Inter", "font_px": 78}, {"font": "Anton"})
    assert zus == {"font": "Anton", "font_px": 78}


def test_ohne_clipstil_bleibt_die_marke_unveraendert():
    assert act.caption_style_zusammen({"highlight_color": "#ffd700"}, {}) == {"highlight_color": "#ffd700"}
    assert act.caption_style_zusammen({"highlight_color": "#ffd700"}, None) == {"highlight_color": "#ffd700"}


def test_ohne_beides_bleibt_es_leer():
    assert act.caption_style_zusammen(None, None) == {}


# -- Welches Preset die Grundlage ist --------------------------------------------------------------
def test_eine_wahl_im_clipstil_sticht_das_format():
    assert act.caption_basis_preset("tiktok", {}, "9:16", {"preset": "linkedin_static"}) == "linkedin_static"


def test_ohne_wahl_entscheidet_weiter_das_format():
    ohne = act.caption_preset_for("tiktok", {}, "9:16")
    assert act.caption_basis_preset("tiktok", {}, "9:16", {}) == ohne
    assert act.caption_basis_preset("tiktok", {}, "9:16", {"preset": "gibtsnicht"}) == ohne


# -- Schriftdatei fehlt ----------------------------------------------------------------------------
def test_fehlende_schriftdatei_wird_gesagt_statt_stillschweigend_ersetzt():
    """libass fällt sonst auf irgendetwas zurück, und der Render sieht aus wie ein Fehler."""
    fehlend = next((s for s in c.schriften()["schriften"] if not (act.render.default_fonts_dir() / s["datei"]).is_file()), None)
    if fehlend is None:
        pytest.skip("alle Schriftdateien liegen vor")
    font, hinweis = act.caption_schrift({"font": fehlend["id"]}, "Inter")
    assert font == "Inter"
    assert hinweis and fehlend["datei"] in hinweis


def test_vorhandene_schrift_wird_genommen():
    font, hinweis = act.caption_schrift({"font": "Inter"}, None)
    assert font == "Inter" and hinweis is None


def test_ohne_wahl_bleibt_der_markenfont():
    assert act.caption_schrift({}, "Hausschrift") == ("Hausschrift", None)


def test_unbekannte_schrift_wird_gesagt():
    font, hinweis = act.caption_schrift({"font": "Comic Sans"}, "Hausschrift")
    assert font == "Hausschrift" and hinweis and "Comic Sans" in hinweis


# -- Das Ergebnis muss durch den ASS-Erzeuger gehen -------------------------------------------------
def _woerter(n: int) -> list[dict]:
    return [{"text": f"Wort{i}", "start": i * 0.4, "end": i * 0.4 + 0.35, "speaker": "SPEAKER_00"} for i in range(n)]


def test_ein_eingestellter_stil_landet_im_ass():
    p = c.style_anwenden(
        c.preset_for("tiktok_words"),
        {"font": "Anton", "font_px": 120, "base_color": "#00FF00", "words_per_card": 2, "bold": False},
    )
    ass = c.to_ass(_woerter(6), preset=p)
    assert "Anton" in ass
    assert ",120," in ass
    assert "&H0000FF00" in ass
    # Zwei Wörter je Einblendung heißt drei Einblendungen für sechs Wörter, bei Highlight je Wort
    # ein Ereignis: sechs Zeilen.
    assert ass.count("Dialogue:") == 6


def test_ohne_highlight_gibt_es_eine_einblendung_je_karte():
    p = c.style_anwenden(c.preset_for("tiktok_words"), {"words_per_card": 2, "highlight_words": False})
    ass = c.to_ass(_woerter(6), preset=p)
    assert ass.count("Dialogue:") == 3


# -- Grossbuchstaben -------------------------------------------------------------------------------
def test_grossbuchstaben_landen_im_ass():
    """all_caps stand seit jeher im Preset, wurde aber nirgends angewendet."""
    woerter = [{"text": "Strasse", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"}]
    p = c.style_anwenden(c.preset_for("tiktok_words"), {"all_caps": True})
    assert "STRASSE" in c.to_ass(woerter, preset=p)
    assert "Strasse" in c.to_ass(woerter, preset=c.preset_for("tiktok_words"))


def test_eszett_wird_vor_der_laengenrechnung_umgewandelt():
    """Aus ß wird SS, also ein Zeichen mehr. Wer erst rechnet und dann umwandelt, laeuft ueber."""
    woerter = [{"text": "Strauß", "start": 0.0, "end": 0.5, "speaker": "SPEAKER_00"}]
    ass = c.to_ass(woerter, preset=c.style_anwenden(c.preset_for("tiktok_words"), {"all_caps": True}))
    assert "STRAUSS" in ass
