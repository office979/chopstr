"""Freigaberelevante Behauptungen (``pipeline.release_gate``): Fälle aus ``editorial_v1`` und Negativfälle.

Das alte Flag ``claim`` (``story_graph.claims_in``) bleibt unverändert; hier steht, welche Sätze die
automatische Freigabe wirklich aufhalten (``docs/ENTSCHEIDUNGEN.md`` P27).
"""

from __future__ import annotations

import pytest

from chopstr_worker.pipeline import story_graph
from chopstr_worker.pipeline.release_gate import release_relevant_claims
from tests.editorial_v1 import harness


def _case_text(case_id: str) -> str:
    return " ".join(str(w["text"]) for w in harness.load_case(case_id)["words"])


def test_misrecognized_number_is_release_relevant():
    """Die unsicher erkannte Zahl mit Währung muss ein Mensch am Audio prüfen."""
    assert release_relevant_claims(_case_text("misrecognized_number_or_name")) == [
        "Bei uns hat das im ersten Jahr rund 40.000 Euro gespart."
    ]


def test_conditional_recommendation_is_not_release_relevant():
    """„weil jeder wusste“ und „jederzeit“ lösten das alte Flag aus; eine Behauptung zum Prüfen ist es nicht."""
    text = _case_text("conditional_recommendation")
    assert story_graph.claims_in(text)
    assert release_relevant_claims(text) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Was ich gelernt habe: Preise sind Positionierung.",
        "Allerdings hat das länger gedauert als gedacht.",
        "Im Büro würde ich es jederzeit wieder machen.",
    ],
)
def test_substrings_do_not_count_without_word_boundaries(sentence):
    assert story_graph.claims_in(sentence), "das alte Flag trifft hier ohne Wortgrenze"
    assert release_relevant_claims(sentence) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Bei uns hat das gut funktioniert, weil jeder wusste, wer wen vertritt.",
        "Dadurch sind wir schneller geworden.",
        "Das war 2024, also bevor die Preise angezogen haben.",
        "Sie hat die Zahl der Lieferanten von zwölf auf vier reduziert.",
        "Mein früherer Vertriebschef hat immer gesagt, dass Kaltakquise tot ist.",
        "Nein, nie ernsthaft.",
        "[2] (SPEAKER_00) Ich hab danach im leeren Büro gestanden.",
        "Wir haben ein Jahr gebraucht.",
        "Die Vier-Tage-Woche hat sich bewährt.",
        "Achtung, das ist neu.",
        "Und dann kam der Einkauf.",
        "Bei uns hilft jeder mit.",
    ],
)
def test_not_release_relevant(sentence):
    assert release_relevant_claims(sentence) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Wir haben 40 Prozent Marge verloren.",
        "Die Marge lag bei 12,5 % im Jahr davor.",
        "Das hat uns 500 € gekostet.",
        "Das hat uns € 500 gekostet.",
        "Der Umsatz lag bei 3 Mio. im ersten Jahr.",
        "Wir haben zwei Millionen investiert.",
        "Wir waren zehnmal so schnell.",
        "Das ging 3-mal schneller.",
        "Wir haben doppelt so viele Anfragen.",
        "Die Hälfte der Bestellungen kam zurück.",
        "Wir haben das drei Jahre lang gemacht.",
        "Nach sechs Monaten war die Marge weg.",
        "Wir haben 200 Kunden gewonnen.",
        "Das Ergebnis ist garantiert.",
        "Es ist bewiesen, dass das wirkt.",
        "Das gilt für jede Firma.",
        "Das braucht man nie.",
        "Grundsätzlich wollen alle Kunden dasselbe.",
        # Proben aus dem Review der Nacharbeit
        "Das funktioniert immer bei allen Kunden.",
        "Das klappt nie.",
        "Das kostet 12 Franken.",
        "Das kostet 50 CHF.",
        "Fünfzehn Prozent sind weg.",
        "Wir haben 2 Milliarden umgesetzt.",
        "Die Marge stieg um 40 Prozentpunkte.",
        "Ein Drittel der Kunden kauft.",
        "Wir haben 500 Mitarbeiter.",
        # weitere Einheiten, Zahlwörter, Vergleiche und Belegwörter
        "Das hat uns fünfundzwanzig Stunden gekostet.",
        "Wir haben vierzigtausend Euro gespart.",
        "Das dauert zwei Wochen.",
        "Nach 3 Tagen war es fertig.",
        "Nach 1 Jahr war es fertig.",
        "Das kostet 20 Dollar.",
        "Das kostet $20 im Monat.",
        "Das kostet CHF 50 im Monat.",
        "Der Umsatz lag bei 3 Mrd. im ersten Jahr.",
        "Der Umsatz hat sich verdoppelt.",
        "Die Kosten haben sich verdreifacht.",
        "Das ist halb so teuer.",
        "Ein Viertel ging verloren.",
        "Ein Fünftel kam zurück.",
        "Wir sind die Nummer eins.",
        "Das ist belegt.",
        "Das ist erwiesen.",
        "Das zeigt die wissenschaftliche Forschung.",
        "Das hilft jeder Firma.",
        "Alle Menschen wollen das.",
    ],
)
def test_release_relevant(sentence):
    assert release_relevant_claims(sentence) == [sentence]


def test_returns_each_relevant_sentence_once_in_text_order():
    text = (
        "[0] (SPEAKER_00) Wir haben 40 Prozent Marge verloren, und das gilt für jede Firma.\n"
        "[1] (SPEAKER_00) Der eigentliche Grund war ein falsches Preismodell.\n"
        "[2] (SPEAKER_00) Wir haben 2019 die Preise um 30 Prozent gesenkt."
    )
    assert release_relevant_claims(text) == [
        "Wir haben 40 Prozent Marge verloren, und das gilt für jede Firma.",
        "Wir haben 2019 die Preise um 30 Prozent gesenkt.",
    ]


def test_empty_text():
    assert release_relevant_claims("") == []
