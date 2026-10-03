"""Verbklammer über die Schnittgrenze (AP3) und deterministischer Rückfall ohne spaCy.

Befund 2: das alte Tor prüfte Anfang und Ende gegen Sperrbereiche innerhalb desselben Satzes und war
damit per Konstruktion immer legal; ohne Modell galt es still als bestanden. Hier wird der Text aus
Vorsatz und Folgesatz zusammen geprüft, ohne spaCy über drei heuristische Signale.
"""

from __future__ import annotations

import pytest

from chopstr_worker import editorial
from chopstr_worker.pipeline import dach_nlp


def words(text: str, pause_after: dict[int, float] | None = None, speaker: str = "S0") -> list[dict]:
    pause_after = pause_after or {}
    out, t = [], 0.0
    for k, tok in enumerate(text.split()):
        out.append({"text": tok, "start": round(t, 3), "end": round(t + 0.3, 3), "speaker": speaker})
        t += 0.32 + pause_after.get(k, 0.0)
    return out


def split(text: str, at: int) -> tuple[list[dict], list[dict]]:
    w = words(text)
    return w[:at], w[at:]


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)


# -- Signal (a): trennbares Verb -------------------------------------------------------------------


def test_separable_particle_after_the_cut_is_an_open_bracket():
    r = dach_nlp.bracket_heuristic(*split("Wir fangen morgen an.", 3))
    assert r["open"] is True and r["signal"] == "separable_particle"
    assert r["available"] == "heuristic"
    assert "an" in r["detail"]


def test_preposition_with_object_is_no_separable_particle():
    assert dach_nlp.bracket_heuristic(*split("Wir fangen morgen an der Kasse an.", 3))["open"] is False
    assert dach_nlp.bracket_heuristic(*split("Das ist gut. Weiter.", 3))["open"] is False


# -- Signal (b): Nebensatz ohne Verb am Ende -------------------------------------------------------


def test_subordinate_clause_without_final_verb_is_open():
    r = dach_nlp.bracket_heuristic(*split("Ich glaube, dass wir das Projekt schaffen.", 4))
    assert r["open"] is True and r["signal"] == "subordinate_clause"
    assert "dass" in r["detail"]


def test_subordinate_clause_with_final_verb_is_closed():
    assert dach_nlp.bracket_heuristic(*split("Es lief gut, weil jeder wusste, wer wen vertritt. Danach kam mehr.", 9))["open"] is False
    assert dach_nlp.bracket_heuristic(*split("Ich glaube, dass wir das schaffen. Dann sehen wir weiter.", 6))["open"] is False


# -- Signal (c): Hilfs- oder Modalverb ohne Partizip oder Infinitiv ---------------------------------


def test_auxiliary_without_participle_and_participle_after_cut_is_open():
    """Plan AP3: „Wir haben das letzte Jahr“ | „nicht gemacht.“ schlägt an."""
    r = dach_nlp.bracket_heuristic(*split("Wir haben das letzte Jahr nicht gemacht.", 5))
    assert r["open"] is True and r["signal"] == "auxiliary_bracket"
    assert "haben" in r["detail"] and "gemacht" in r["detail"]


def test_modal_verb_with_infinitive_after_cut_is_open():
    r = dach_nlp.bracket_heuristic(*split("Wir müssen die Preise noch einmal ändern.", 4))
    assert r["open"] is True and r["signal"] == "auxiliary_bracket"


def test_closed_bracket_or_new_finite_verb_is_no_signal():
    assert dach_nlp.bracket_heuristic(*split("Wir haben das gemacht und dann gewartet.", 4))["open"] is False
    assert dach_nlp.bracket_heuristic(*split("Das ist gut Wir haben gestern gesprochen.", 3))["open"] is False
    assert dach_nlp.bracket_heuristic(*split("Wir haben das letzte Jahr. Nicht gemacht haben wir nichts.", 5))["open"] is False


def test_no_bracket_across_a_speaker_change():
    left = words("Wir haben das letzte Jahr", speaker="A")
    right = words("nicht gemacht.", speaker="B")
    assert dach_nlp.bracket_heuristic(left, right)["open"] is False


def test_participle_and_infinitive_shapes():
    for w in ("gemacht", "angefangen", "verkauft", "gegessen", "erzählt", "funktioniert"):
        assert dach_nlp.is_participle(w), w
    for w in ("Gemacht", "gegen", "gestern", "genau", "geht"):
        assert not dach_nlp.is_participle(w), w
    for w in ("machen", "ändern", "sammeln"):
        assert dach_nlp.is_infinitive(w), w
    for w in ("einen", "morgen", "stattdessen", "Machen"):
        assert not dach_nlp.is_infinitive(w), w


# -- Satzpaare mit Pause: dieselbe Heuristik speist den Pause-Kandidaten aus AP2 ---------------------


def test_pause_inside_bracket_is_no_sentence_end():
    w = words("Wir haben das letzte Jahr nicht gemacht.", {4: 1.0})
    assert dach_nlp.sentence_end_kind(w, 4, "v2") == "none"
    w = words("Wir haben dann stattdessen Newsletter gemacht.", {3: 0.9})
    assert dach_nlp.sentence_end_kind(w, 3, "v2") == "none"


# -- Schnitt im Transkript -------------------------------------------------------------------------


def test_bracket_open_at_cut_checks_previous_and_following_sentence_together():
    w = words("Das ist klar. Wir haben das letzte Jahr nicht gemacht. Dann kam Neues.")
    cut = next(i for i, x in enumerate(w) if x["text"] == "nicht")
    r = dach_nlp.bracket_open_at_cut(w, cut)
    assert r["open"] is True and r["available"] == "heuristic"
    clean = next(i for i, x in enumerate(w) if x["text"] == "Dann")
    assert dach_nlp.bracket_open_at_cut(w, clean)["open"] is False


def test_bracket_open_at_cut_at_the_edges_and_with_fallback_off():
    w = words("Wir haben das letzte Jahr nicht gemacht.")
    assert dach_nlp.bracket_open_at_cut(w, 0)["available"] == "none"
    assert dach_nlp.bracket_open_at_cut(w, len(w))["open"] is False
    off = dach_nlp.bracket_open_at_cut(w, 5, fallback="off")
    assert off == {"open": False, "signal": None, "detail": "nicht geprüft", "available": "off"}


def test_bracket_open_at_cut_uses_spacy_ranges_when_a_model_is_loaded(monkeypatch):
    w = words("Wir haben das letzte Jahr nicht gemacht.")
    monkeypatch.setattr(dach_nlp, "nlp", lambda: object())
    monkeypatch.setattr(dach_nlp, "forbidden_cut_ranges", lambda text, wt: [(wt[1]["end"], wt[6]["start"])])
    r = dach_nlp.bracket_open_at_cut(w, 5)
    assert r["open"] is True and r["available"] == "spacy"
    monkeypatch.setattr(dach_nlp, "forbidden_cut_ranges", lambda text, wt: [])
    assert dach_nlp.bracket_open_at_cut(w, 5) == {"open": False, "signal": None, "detail": "keine offene Klammer", "available": "spacy"}


# -- Richtlinie ------------------------------------------------------------------------------------


def test_policy_v2_lists_are_the_lists_of_the_code():
    cfg = editorial.verb_bracket_settings(editorial.load(2))
    assert cfg["fallback"] == "heuristic"
    assert cfg["active"] is True  # ausstieg.verbklammer_nicht_trennen wird gelesen
    assert cfg["lists"]["particles"] == dach_nlp.VERB_PARTICLES
    assert cfg["lists"]["subordinators"] == dach_nlp.SUBORDINATORS
    assert cfg["lists"]["auxiliaries"] == dach_nlp.AUXILIARY_FORMS
    assert editorial.verb_bracket_settings(editorial.load(1)) is None


def test_policy_lists_feed_the_heuristic():
    left, right = split("Wir fangen morgen an.", 3)
    assert dach_nlp.bracket_heuristic(left, right, particles=("los",))["open"] is False
