"""Zoom als Betonung: die Kurve, das Lesen und die Automatik."""

from __future__ import annotations

from chopstr_worker.pipeline import effekte as ef


def test_hinein_faehrt_sanft_und_bleibt_dann():
    """Vorher fuhr der Zoom zurueck, solange der Block lief. Das sah aus wie Wackeln: eine Bewegung
    hin und gleich wieder her, mitten im Satz."""
    e = [ef.Effekt("zoom_in", 2.0, 2.0)]
    assert ef.faktor(e, 1.9) == 1.0
    assert ef.faktor(e, 2.0) == 1.0
    assert abs(ef.faktor(e, 2.0 + ef.ANSTIEG_S) - (1 + ef.STAERKE)) < 1e-9
    for t in (2.5, 3.0, 3.5, 4.0):
        assert abs(ef.faktor(e, t) - (1 + ef.STAERKE)) < 1e-9
    assert ef.faktor(e, 4.01) == 1.0


def test_die_fahrt_setzt_ohne_knick_an_und_kommt_ohne_knick_an():
    """Ein linearer Anstieg setzt sichtbar an und bricht sichtbar ab - genau das nimmt man als
    Ruckeln wahr. Die Steigung muss an beiden Enden gegen null gehen."""
    e = [ef.Effekt("zoom_in", 0.0, 2.0)]
    steigung = lambda t: (ef.faktor(e, t + 0.01) - ef.faktor(e, t)) / 0.01  # noqa: E731
    assert abs(steigung(0.0)) < 0.05
    assert abs(steigung(ef.ANSTIEG_S - 0.02)) < 0.15
    assert steigung(ef.ANSTIEG_S / 2) > 0.2


def test_heraus_macht_das_bild_kleiner_und_laesst_es_so():
    """Spiegelbild von „hinein". Rundherum steht Schwarz, dafuer gibt es die Reserve in der Kette."""
    e = [ef.Effekt("zoom_out", 0.0, 2.0)]
    assert abs(ef.faktor(e, 0.0) - 1.0) < 1e-9
    assert abs(ef.faktor(e, ef.ANSTIEG_S) - (1 - ef.STAERKE)) < 1e-9
    assert abs(ef.faktor(e, 1.5) - (1 - ef.STAERKE)) < 1e-9


def test_ein_effekt_wirkt_nur_solange_sein_block_laeuft():
    """Sonst addieren sich zwei Effekte, und nach dem dritten ist das Bild eine Briefmarke."""
    for art in ef.ARTEN:
        e = [ef.Effekt(art, 1.0, 1.5)]
        assert ef.faktor(e, 2.51) == 1.0
        assert ef.faktor(e, 5.0) == 1.0


def test_ausserhalb_seiner_zeit_tut_ein_effekt_nichts():
    e = [ef.Effekt("zoom_in", 5.0, 1.0)]
    assert ef.faktor(e, 0.0) == 1.0
    assert ef.faktor(e, 4.99) == 1.0
    assert ef.faktor(e, 6.01) == 1.0


def test_lesen_wirft_unbrauchbares_weg():
    roh = [
        {"art": "zoom_in", "ab_s": 1.0, "dauer_s": 1.4},
        {"art": "glitzer", "ab_s": 2.0, "dauer_s": 1.0},
        {"art": "zoom_in", "ab_s": 99.0, "dauer_s": 1.0},
        "kein Objekt",
        {"art": "zoom_out", "ab_s": 5.0, "dauer_s": 0.01},
    ]
    aus = ef.lesen(roh, 30.0)
    # Unbekannte Art und Zeit ausserhalb des Clips fliegen raus. Eine zu kurze Dauer nicht: der
    # Nutzer hat den Effekt gesetzt, er wird auf das Mindestmass gebracht statt verworfen.
    assert [e.art for e in aus] == ["zoom_in", "zoom_out"]
    assert aus[1].dauer_s == ef.MIN_DAUER_S


def test_lesen_kuerzt_statt_zu_verwerfen():
    """Der Nutzer hat den Effekt gesetzt; seitdem ist nur der Schnitt kuerzer geworden."""
    aus = ef.lesen([{"art": "zoom_in", "ab_s": 9.0, "dauer_s": 5.0}], 10.0)
    assert len(aus) == 1 and abs(aus[0].dauer_s - 1.0) < 1e-9


def test_lesen_loest_ueberschneidungen_auf():
    aus = ef.lesen(
        [{"art": "zoom_in", "ab_s": 1.0, "dauer_s": 2.0}, {"art": "zoom_in", "ab_s": 2.0, "dauer_s": 2.0}], 30.0
    )
    assert aus[1].ab_s >= aus[0].ab_s + aus[0].dauer_s


def test_zwei_effekte_addieren_sich_nie_uebereinander():
    aus = ef.lesen(
        [{"art": "zoom_in", "ab_s": 1.0, "dauer_s": 2.0}, {"art": "zoom_out", "ab_s": 1.5, "dauer_s": 2.0}], 30.0
    )
    for t in [x / 20 for x in range(0, 200)]:
        assert ef.faktor(aus, t) <= 1 + ef.STAERKE + 1e-9


def _woerter(paare: list[tuple[float, str]]) -> list[dict]:
    return [{"start": t, "end": t + 0.3, "text": w} for t, w in paare]


def test_automatik_betont_zahlen():
    # Ausgeschriebene Zahlwoerter erkennt die Regel bewusst nicht: das Transkript normalisiert
    # Zahlen zu Ziffern (nlp.normalize_numbers), und eine Wortliste fuer „vierzehntausend" waere
    # in jeder Sprache ein Fass ohne Boden.
    w = _woerter([(0.5, "Also"), (6.0, "14.000"), (6.5, "Euro"), (12.0, "40.000")])
    aus = ef.automatisch(w, 30.0)
    assert len(aus) == 2
    assert all(e.art == "zoom_in" for e in aus)
    # Kurz vor dem Wort, damit die Bewegung auf dem Wort ihren Hoehepunkt hat.
    assert aus[0].ab_s < 6.0


def test_automatik_laesst_die_erste_sekunde_in_ruhe():
    """Ein Zoom auf das erste Wort wirkt wie ein Fehler."""
    assert ef.automatisch(_woerter([(0.2, "15"), (0.6, "Prozent")]), 30.0) == []


def test_automatik_setzt_nicht_zweimal_dicht_hintereinander():
    w = _woerter([(5.0, "12"), (5.6, "13"), (6.1, "14")])
    aus = ef.automatisch(w, 30.0)
    assert len(aus) == 1


def test_automatik_setzt_hoechstens_drei():
    w = _woerter([(float(2 + i * 5), str(i)) for i in range(10)])
    assert len(ef.automatisch(w, 90.0)) <= 3


def test_automatik_betont_ankuendigungen():
    aus = ef.automatisch(_woerter([(2.0, "Das"), (6.0, "Entscheidend"), (6.5, "ist")]), 30.0)
    assert len(aus) == 1


def test_automatik_schweigt_ohne_anlass():
    assert ef.automatisch(_woerter([(2.0, "Und"), (3.0, "dann"), (4.0, "halt")]), 30.0) == []


def test_der_ffmpeg_ausdruck_bildet_dieselbe_kurve():
    """Zwei Umsetzungen derselben Kurve: die Python-Rechnung ist die Wahrheit, der Ausdruck muss
    ihr folgen. Gerechnet wird er hier mit denselben Regeln, die ffmpeg anwendet."""
    import math

    e = [ef.Effekt("zoom_in", 2.0, 1.4), ef.Effekt("zoom_out", 6.0, 2.0)]
    ausdruck = ef.ffmpeg_ausdruck(e, 25)
    umgebung = {
        "between": lambda x, a, b: 1.0 if a <= x <= b else 0.0,
        "lte": lambda a, b: 1.0 if a <= b else 0.0,
        "pow": math.pow,
        "if": lambda c, a, b=0.0: a if c else b,
    }
    for on in range(0, 250):
        wert = eval(ausdruck.replace("if(", "iff("), {"iff": umgebung["if"], **umgebung, "on": on})  # noqa: S307
        # Der Ausdruck liefert die zoompan-Zahl, also RESERVE mal den sichtbaren Faktor.
        assert abs(wert / ef.RESERVE - ef.faktor(e, on / 25)) < 1e-9, f"Frame {on}"


def test_ohne_effekte_bleibt_der_ausdruck_der_ruhezustand():
    """Der Ruhezustand ist RESERVE und nicht 1: das Bild liegt auf einer groesseren schwarzen
    Flaeche, und genau dort sieht man es unveraendert."""
    assert float(ef.ffmpeg_ausdruck([], 25)) == ef.RESERVE
