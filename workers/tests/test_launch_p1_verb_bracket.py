"""Verbklammer-Erweiterung (Lane P1, Fassung 2): zu-Infinitiv, Korrelate, trennbare Partikel ohne Satzzeichen.

Je Konstruktion ein Fall, in dem die offene Klammer erkannt wird, und ein zulässiges Gegenbeispiel, das durchgeht.
Ohne ``rule`` (Standard ``v1``) bleibt alles wie vor Lane P1, weil die Satzgrenzen und ihr Web-Port die Funktion
ohne ``rule`` aufrufen (Parität P5).
"""

from __future__ import annotations

import pytest

from chopstr_worker.pipeline import dach_nlp


def words(text: str, speaker: str = "S0") -> list[dict]:
    return [{"text": tok, "start": round(k * 0.4, 3), "end": round(k * 0.4 + 0.3, 3), "speaker": speaker} for k, tok in enumerate(text.split())]


def cut(text: str, at: int, rule: str = "v2") -> dict:
    w = words(text)
    return dach_nlp.bracket_heuristic(w[:at], w[at:], rule=rule)


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)


# -- zu-Infinitiv mit Einleitung (um, ohne, statt, anstatt) -------------------------------------------


@pytest.mark.parametrize(
    "text,at,intro",
    [
        ("Wir sparen jeden Monat, um mehr zu investieren.", 5, "um"),
        ("Er ging, ohne ein Wort zu sagen.", 4, "ohne"),
        ("Sie telefoniert, statt eine Mail zu schreiben.", 4, "statt"),
        ("Er wartet, anstatt endlich anzufangen.", 4, "anstatt"),
    ],
)
def test_introducer_with_zu_infinitive_after_the_cut_is_open(text, at, intro):
    r = cut(text, at)
    assert r["open"] is True and r["signal"] == "zu_infinitive" and intro in r["detail"]
    assert cut(text, at, rule="v1")["open"] is False  # vor Lane P1 nicht erkannt


def test_preposition_um_ohne_without_zu_infinitive_passes():
    assert cut("Wir treffen uns um 8 Uhr und reden dann.", 4)["open"] is False
    assert cut("Er trinkt Kaffee ohne Zucker und Milch.", 5)["open"] is False
    # der Infinitiv gehört zur eigenen Einleitung rechts, der Satz links ist zu Ende
    assert cut("Wir sparen jeden Monat, um mehr zu investieren.", 4)["open"] is False


# -- einfacher zu-Infinitiv -----------------------------------------------------------------------


def test_simple_zu_infinitive_after_the_cut_is_open():
    r = cut("Wir haben beschlossen das Projekt zu stoppen.", 3)
    assert r["open"] is True and r["signal"] == "zu_infinitive" and "stoppen" in r["detail"]
    r = cut("Wir versuchen zu sparen.", 3)  # Schnitt zwischen „zu" und Infinitiv
    assert r["open"] is True and r["signal"] == "zu_infinitive"


def test_zu_as_preposition_or_degree_passes():
    assert cut("Wir fahren am Wochenende zu meinen Eltern.", 4)["open"] is False
    assert dach_nlp.zu_infinitive_end(words("zu offen"), 0) is None
    assert dach_nlp.zu_infinitive_end(words("zu großen Teilen"), 0) is None
    assert dach_nlp.zu_infinitive_end(words("zu sein"), 0) == 1
    assert dach_nlp.zu_infinitive_end(words("zusammenzuarbeiten"), 0) == 0
    # rechts beginnt mit Konnektor ein eigener Teilsatz
    assert cut("Wir sind fertig weil wir nichts zu tun haben.", 3)["open"] is False


# -- Korrelate -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,at,first",
    [
        ("Das Produkt ist zwar teuer, aber es lohnt sich.", 5, "zwar"),
        ("Entweder wir handeln jetzt oder wir verlieren.", 4, "entweder"),
        ("Je früher wir anfangen, desto besser.", 4, "je"),
        ("Das gilt nicht nur für Kunden, sondern auch für Händler.", 5, "nicht nur"),
        ("Wir haben weder Zeit noch Geld.", 4, "weder"),
        ("Das gilt sowohl für Kunden als auch für Händler.", 5, "sowohl"),
    ],
)
def test_correlate_split_by_the_cut_is_open(text, at, first):
    r = cut(text, at)
    assert r["open"] is True and r["signal"] == "correlate" and first in r["detail"]
    assert cut(text, at, rule="v1")["open"] is False


def test_closed_or_false_correlates_pass():
    assert cut("Das Produkt ist zwar teuer, aber es lohnt sich.", 6)["open"] is False  # beide Teile links
    assert cut("Es geht um den Preis, und zwar um den Endpreis.", 9)["open"] is False  # „und zwar"
    assert cut("Wir zahlen je Person zehn Euro und fertig.", 5)["open"] is False  # „je" ohne Komparativ


def test_open_correlates_over_a_clip_span():
    assert dach_nlp.open_correlates(words("Das ist zwar teuer. Und dann kam nichts mehr.")) == [
        {"first": "zwar", "index": 2, "expected": ("aber", "doch", "jedoch", "allerdings")}
    ]
    assert dach_nlp.open_correlates(words("Das ist zwar teuer. Aber es lohnt sich.")) == []
    assert dach_nlp.open_correlates(words("Aber es lohnt sich.")) == []  # zweiter Teil allein


# -- trennbare Partikel ohne Satzzeichen -----------------------------------------------------------


def test_particle_without_punctuation_is_open():
    for text, at in (("Wir fangen morgen an", 3), ("Wir fangen morgen an und dann schauen wir.", 3), ("Er kommt heute mit", 3)):
        r = cut(text, at)
        assert r["open"] is True and r["signal"] == "separable_particle", text
        assert cut(text, at, rule="v1")["open"] is False, text


def test_particle_used_as_preposition_passes():
    assert cut("Wir treffen uns morgen an der Kasse.", 4)["open"] is False
    assert cut("Er kommt mit dem Auto.", 2)["open"] is False
    assert cut("Wir gehen bei Regen nicht raus.", 2)["open"] is False


# -- Schutz und Parität -------------------------------------------------------------------------------


def test_speaker_change_and_sentence_end_close_every_extension():
    left = words("Wir haben beschlossen", speaker="A")
    right = words("das Projekt zu stoppen.", speaker="B")
    assert dach_nlp.bracket_heuristic(left, right, rule="v2")["open"] is False
    assert cut("Das ist zwar teuer. Dann kam nichts.", 4)["open"] is False


def test_default_rule_is_v1_and_unknown_rule_fails():
    w = words("Wir sparen jeden Monat, um mehr zu investieren.")
    assert dach_nlp.bracket_heuristic(w[:5], w[5:]) == dach_nlp.bracket_heuristic(w[:5], w[5:], rule="v1")
    with pytest.raises(ValueError):
        dach_nlp.bracket_heuristic(w[:5], w[5:], rule="v3")
    assert "um" not in dach_nlp.SUBORDINATORS  # Satzgrenzen und Web-Port unverändert
    assert dach_nlp.SUBORDINATORS_V2[-4:] == ("um", "ohne", "statt", "anstatt")


def test_forbidden_cut_ranges_v2_without_spacy():
    w = words("Wir sparen, um mehr zu investieren. Zwar teuer, aber gut.")
    text = " ".join(x["text"] for x in w)
    assert dach_nlp.forbidden_cut_ranges(text, w) == []  # Standard wie bisher
    ranges = dach_nlp.forbidden_cut_ranges(text, w, rule="v2")
    assert ranges == [(w[2]["end"], w[5]["start"]), (w[6]["end"], w[8]["start"])]
    assert not dach_nlp.cut_is_legal((w[3]["end"] + w[4]["start"]) / 2, ranges)
    assert dach_nlp.cut_is_legal((w[5]["end"] + w[6]["start"]) / 2, ranges)
