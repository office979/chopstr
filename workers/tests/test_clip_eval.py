"""Tests für die Messlatte (eval/clip_eval.py).

Ein Messwerkzeug, dem man nicht trauen kann, ist schlimmer als keines: es lenkt die nächsten
Schritte in die falsche Richtung. Deshalb wird hier vor allem geprüft, dass die Prüfungen auch
„nein" sagen können und dass der heikle Fall Artikel gegen Demonstrativpronomen stimmt.
"""

from __future__ import annotations

import importlib.util

import pytest

from chopstr_worker.pipeline import dach_nlp
from eval import clip_eval

SPACY_DA = importlib.util.find_spec("spacy") is not None and dach_nlp.nlp() is not None


def w(text: str, start: float, ende: float, speaker: str = "SPEAKER_00") -> dict:
    return {"text": text, "start": start, "end": ende, "speaker": speaker}


def satz(woerter: list[str], ab: float = 0.0, schritt: float = 0.4, speaker: str = "SPEAKER_00") -> list[dict]:
    """Baut Wortzeiten ohne Lücken, damit nur Satzzeichen die Satzgrenze setzen."""
    out = []
    t = ab
    for text in woerter:
        out.append(w(text, t, t + schritt, speaker))
        t += schritt
    return out


# -- Grenzen -------------------------------------------------------------------------------------
def test_sauberer_clip_wird_als_sauber_erkannt():
    words = satz(["Wir", "haben", "damals", "alles", "verloren."]) + satz(["Danach", "lief", "es", "besser."], ab=2.0)
    cand = {"start_s": 0.0, "end_s": 2.0}
    b = clip_eval.check_boundaries(cand, words)
    assert b["satzanfang"] is True
    assert b["satzende"] is True
    assert b["beginnt_mit_rueckverweis"] is False
    assert clip_eval.sauber(b) is True


def test_start_mitten_im_satz_faellt_auf():
    """Der Clip beginnt beim dritten Wort, davor endet kein Satz."""
    words = satz(["Wir", "haben", "damals", "alles", "verloren."])
    cand = {"start_s": words[2]["start"], "end_s": words[4]["end"]}
    b = clip_eval.check_boundaries(cand, words)
    assert b["satzanfang"] is False
    assert clip_eval.sauber(b) is False


def test_ende_mitten_im_satz_faellt_auf():
    words = satz(["Wir", "haben", "damals", "alles", "verloren."])
    cand = {"start_s": words[0]["start"], "end_s": words[2]["end"]}
    b = clip_eval.check_boundaries(cand, words)
    assert b["satzende"] is False
    assert clip_eval.sauber(b) is False


def test_eindeutiger_rueckverweis_am_anfang():
    words = satz(["Deswegen", "haben", "wir", "das", "gelassen."])
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    b = clip_eval.check_boundaries(cand, words)
    assert b["beginnt_mit_rueckverweis"] is True
    assert clip_eval.sauber(b) is False


def test_rueckverweis_als_wendung():
    words = satz(["Wie", "gesagt", "war", "das", "ein", "Fehler."])
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    assert clip_eval.check_boundaries(cand, words)["beginnt_mit_rueckverweis"] is True


def test_verneinung_am_rand_faellt_auf():
    words = satz(["Das", "war", "kein", "Zufall."])
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    b = clip_eval.check_boundaries(cand, words)
    assert b["verneinung_am_rand"] is True


def test_verneinung_in_der_mitte_stoert_nicht():
    woerter = ["Wir", "haben", "lange", "geglaubt", "es", "sei", "kein", "Problem", "und", "lagen", "damit", "falsch."]
    words = satz(woerter)
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    b = clip_eval.check_boundaries(cand, words)
    assert b["verneinung_am_rand"] is False


# -- Der heikle Fall: Artikel gegen Demonstrativpronomen -------------------------------------------
@pytest.mark.skipif(not SPACY_DA, reason="Ohne spaCy sind diese Anfänge absichtlich nicht entscheidbar")
def test_artikel_am_anfang_ist_kein_rueckverweis():
    """„Der Empfänger prüft zuerst" ist ein sauberer Anfang, auch wenn es mit „Der" beginnt."""
    words = satz(["Der", "Empfänger", "prüft", "zuerst", "das", "Ergebnis."])
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    assert clip_eval.check_boundaries(cand, words)["beginnt_mit_rueckverweis"] is False


@pytest.mark.skipif(not SPACY_DA, reason="Ohne spaCy sind diese Anfänge absichtlich nicht entscheidbar")
def test_demonstrativpronomen_am_anfang_ist_ein_rueckverweis():
    """„Das ist genau der Punkt" verweist auf etwas, das vorher gesagt wurde."""
    words = satz(["Das", "ist", "genau", "der", "Punkt."])
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    assert clip_eval.check_boundaries(cand, words)["beginnt_mit_rueckverweis"] is True


def test_ohne_spacy_bleibt_mehrdeutiges_unklar(monkeypatch):
    """Lieber „unklar" melden als raten. Ein falscher Alarm macht die Messung unbrauchbar."""
    monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
    words = satz(["Der", "Empfänger", "prüft", "zuerst."])
    cand = {"start_s": words[0]["start"], "end_s": words[-1]["end"]}
    assert clip_eval.check_boundaries(cand, words)["beginnt_mit_rueckverweis"] is None


# -- Treffer -------------------------------------------------------------------------------------
def test_abdeckung_misst_anteil_der_referenzstelle():
    stelle = {"start_s": 100.0, "end_s": 120.0}
    assert clip_eval.abdeckung({"start_s": 100.0, "end_s": 120.0}, stelle) == pytest.approx(1.0)
    assert clip_eval.abdeckung({"start_s": 110.0, "end_s": 120.0}, stelle) == pytest.approx(0.5)
    assert clip_eval.abdeckung({"start_s": 0.0, "end_s": 50.0}, stelle) == pytest.approx(0.0)


def test_vorschlag_der_die_stelle_umschliesst_zaehlt_als_treffer():
    """Etwas Anlauf mitzunehmen ist in Ordnung, nur den Schluss zu erwischen nicht."""
    stellen = [{"start_s": 100.0, "end_s": 120.0, "grund": "Pointe"}]
    umschliessend = [{"start_s": 90.0, "end_s": 130.0}]
    nur_schluss = [{"start_s": 118.0, "end_s": 140.0}]
    assert clip_eval.match_references(umschliessend, stellen, 0.5, 10)["gefunden"] == 1
    assert clip_eval.match_references(nur_schluss, stellen, 0.5, 10)["gefunden"] == 0


def test_jede_stelle_wird_hoechstens_einmal_vergeben():
    stellen = [{"start_s": 100.0, "end_s": 120.0, "grund": "a"}]
    kandidaten = [{"start_s": 100.0, "end_s": 120.0}, {"start_s": 101.0, "end_s": 119.0}]
    ergebnis = clip_eval.match_references(kandidaten, stellen, 0.5, 10)
    assert ergebnis["gefunden"] == 1
    assert ergebnis["trefferquote"] == 1.0


def test_precision_at_k_zaehlt_nur_die_ersten_k():
    stellen = [{"start_s": 500.0, "end_s": 520.0, "grund": "spät"}]
    # Der Treffer steht an Position 3, mit k=2 darf er nicht zählen.
    kandidaten = [
        {"start_s": 0.0, "end_s": 20.0},
        {"start_s": 30.0, "end_s": 50.0},
        {"start_s": 500.0, "end_s": 520.0},
    ]
    ergebnis = clip_eval.match_references(kandidaten, stellen, 0.5, 2)
    assert ergebnis["gefunden"] == 1
    assert ergebnis["precision_at_2"] == 0.0


def test_verpasste_stellen_werden_mit_grund_gemeldet():
    stellen = [{"start_s": 100.0, "end_s": 120.0, "grund": "Klare Zahl mit Beleg"}]
    ergebnis = clip_eval.match_references([{"start_s": 0.0, "end_s": 10.0}], stellen, 0.5, 10)
    assert ergebnis["gefunden"] == 0
    assert ergebnis["verpasst"][0]["grund"] == "Klare Zahl mit Beleg"
