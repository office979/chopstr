"""Ausbeute: wie viele Kandidaten ein Video hergibt.

Hintergrund (gemessen am 27.09.2026 an einer echten Quelle, 9,0 min, 1712 Woerter, 81 Saetze):
die Engine bot 3 Clips an, obwohl im harten Laengenfenster 532 Satzspannen moeglich waren.
Drei Begrenzer wirkten zusammen, keiner davon als redaktionelle Entscheidung gedacht:

  1. ``_anchor_score`` gab 0 zurueck, wenn kein Marker griff, und ``propose_moments`` brach beim
     ersten solchen Anker ab. Marker greifen laut Grundlage auf 2,4 bis 6,2 Prozent der Saetze.
  2. ``PROPOSE_MAX_MOMENTS = 3`` je Kapitel, unabhaengig von dessen Laenge.
  3. ``MAX_PER_CHAPTER = 4`` schnitt in der Engine nochmals ab.

Diese Tests halten die Gegenrichtung fest. Sie pruefen die Ausbeute, nicht den Geschmack: welcher
Clip etwas taugt, entscheidet der Mensch am Werkzeug.
"""

from __future__ import annotations

import pytest

from chopstr_worker import editorial, heuristic_llm
from chopstr_worker.pipeline import segment, story_engine


@pytest.fixture
def pol():
    return editorial.load()


# -- Die Grundlage kennt die Ausbeute -------------------------------------------------------
def test_grundlage_hat_den_abschnitt(pol):
    assert pol.kandidaten_je_minute > 0
    assert pol.obergrenze_gesamt >= 20
    assert 0 < pol.ueberlappung_max <= 1
    assert pol.anker_ohne_marker is True


def test_kandidatenzahl_waechst_mit_dem_material(pol):
    kurz = pol.kandidaten_fuer(60)
    lang = pol.kandidaten_fuer(600)
    assert lang > kurz, "ein zehnminuetiges Kapitel muss mehr hergeben als ein einminuetiges"
    assert kurz >= pol.min_je_kapitel
    assert lang <= pol.max_je_kapitel


def test_vorschlaege_liegen_ueber_den_kandidaten(pol):
    """Zwischen Vorschlag und Angebot sieben Tore, Laengenfenster und Ueberlappung aus."""
    for s in (120, 240, 600):
        assert pol.vorschlaege_fuer(s) >= pol.kandidaten_fuer(s)
    assert pol.vorschlag_ueberschuss >= 1.0


def test_ausbeute_faellt_nicht_unter_den_alten_stand(pol):
    """Regressionsschutz: die frueheren Festwerte duerfen nicht zurueckkehren."""
    assert pol.vorschlaege_fuer(240) > 4, "MAX_PER_CHAPTER war 4"
    assert pol.vorschlaege_fuer(240) > 3, "PROPOSE_MAX_MOMENTS war 3"
    assert pol.obergrenze_gesamt > 20, "MAX_CANDIDATES war 20"


# -- Anker entstehen nicht mehr nur an Markern ----------------------------------------------
def test_satz_ohne_marker_kann_anker_sein(pol):
    ohne = {"idx": 0, "text": "Wir sind dann nach Hause gefahren und haben uns hingesetzt."}
    assert heuristic_llm._anchor_score(ohne, pol) > 0


def test_marker_bleibt_ein_vorteil(pol):
    ohne = {"idx": 0, "text": "Wir sind dann nach Hause gefahren und haben uns hingesetzt."}
    mit = {"idx": 1, "text": "Das Entscheidende ist, dass 80 Prozent daran scheitern."}
    assert heuristic_llm._anchor_score(mit, pol) > heuristic_llm._anchor_score(ohne, pol)


# -- Ende zu Ende ---------------------------------------------------------------------------
def _saetze(n: int) -> list[dict]:
    """Gleichfoermiges Transkript ohne jeden Marker: der ungünstigste Fall fuer die alte Logik."""
    words = []
    t = 0.0
    for i in range(n):
        for w in f"Satz {i} laeuft hier ganz ruhig und ohne jede Auffaelligkeit weiter.".split():
            words.append({"text": w, "start": round(t, 2), "end": round(t + 0.45, 2), "speaker": "S0"})
            t += 0.5
        words[-1]["text"] += "."
        t += 0.6
    return words


def test_markerloses_material_liefert_trotzdem_kandidaten(pol):
    """Frueher: null Anker, null Vorschlaege. Jetzt deckt die Auswahl das Material ab."""
    words = _saetze(60)
    sents = segment.sentences_from_words(words)
    dauer = sents[-1].end - sents[0].start
    moments = heuristic_llm.propose_moments(segment.numbered(sents))["moments"]
    assert len(moments) >= 3, f"markerloses Material ergab nur {len(moments)} Vorschlaege"
    assert len(moments) <= pol.vorschlaege_fuer(dauer)


def test_anker_halten_mindestabstand():
    words = _saetze(60)
    sents = segment.sentences_from_words(words)
    moments = heuristic_llm.propose_moments(segment.numbered(sents))["moments"]
    starts = sorted(m["first_sent"] for m in moments)
    for a, b in zip(starts, starts[1:]):
        assert b - a >= 1, "zwei Vorschlaege duerfen nicht am selben Satz beginnen"


def test_ueberlappung_haelt_den_dokumentierten_fall(pol):
    """Der Fall aus BP CW bleibt erfasst: halb enthalten ist keine Auswahl, sondern Redundanz."""
    assert pol.ueberlappung_max <= 0.49, (
        "0 bis 19,6 s neben 9,9 bis 87,9 s hat eine Ueberdeckung von 0,49 und muss weichen"
    )
    assert story_engine.gemeinsamer_anteil(0.0, 19.6, 9.9, 87.9) == pytest.approx(0.49, abs=0.01)
