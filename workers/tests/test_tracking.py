"""Tests für Kamerawechsel, Sprecherzuordnung und Drittelregel (pipeline/tracking.py).

Alles ohne Video: Die Entscheidungen hängen an Zahlen, nicht an Pixeln. Genau deshalb liegt die
Logik in einem eigenen Modul.
"""

from __future__ import annotations

import pytest

from chopstr_worker.pipeline import tracking as tr


def abt(t, boxen=(), wechsel=None, mund=()):
    return tr.Abtastung(t=t, boxen=list(boxen), bildwechsel=wechsel, mundbewegung=list(mund))


def box(cx, cy=400, b=200, h=200):
    """Box aus Mittelpunkt, wie sie der Detektor liefert (x, y, w, h)."""
    return (int(cx - b / 2), int(cy - h / 2), b, h)


# -- Kamerawechsel ---------------------------------------------------------------------------------
def test_ohne_wechsel_eine_einstellung():
    a = [abt(i * 0.2, [box(500)], 0.02) for i in range(20)]
    a[0].bildwechsel = None
    assert len(tr.in_einstellungen_teilen(a)) == 1


def test_harter_schnitt_trennt_die_einstellungen():
    """Zehn Abtastpunkte Totale, dann ein Schnitt, dann zehn Naheinstellung."""
    a = [abt(i * 0.2, [box(300)], 0.02) for i in range(10)]
    a[0].bildwechsel = None
    b = [abt(2.0 + i * 0.2, [box(1500)], 0.02) for i in range(10)]
    b[0].bildwechsel = 0.9  # der Schnitt
    einst = tr.in_einstellungen_teilen([*a, *b])
    assert len(einst) == 2
    assert einst[0].abtastungen[0].boxen == [box(300)]
    assert einst[1].abtastungen[0].boxen == [box(1500)]


def test_zu_kurze_einstellung_wird_verschmolzen():
    """Ein Ruckler darf keine eigene Einstellung erzeugen, aus der nichts ableitbar ist."""
    a = [abt(i * 0.2, [box(300)], 0.02) for i in range(10)]
    a[0].bildwechsel = None
    kurz = [abt(2.0, [box(900)], 0.9), abt(2.2, [box(900)], 0.02)]  # nur 0,2 s
    rest = [abt(2.4 + i * 0.2, [box(300)], 0.02) for i in range(10)]
    rest[0].bildwechsel = 0.9  # ein Aufflackern erzeugt zwei Schnitte: hinein und wieder heraus
    einst = tr.in_einstellungen_teilen([*a, *kurz, *rest])
    # Worauf es ankommt: Das Aufflackern bekommt keine eigene Einstellung, aus der sich nichts
    # ableiten liesse, und es bleibt keine Einstellung unter der Mindestdauer uebrig. Dass die
    # beiden Haelften derselben Kamera getrennt bleiben, ist folgenlos: sie liefern dieselbe
    # Sitzposition und damit denselben Ausschnitt.
    assert all(e.dauer_s >= tr.MIN_EINSTELLUNG_S for e in einst)
    assert not any(e.abtastungen[0].boxen == [box(900)] for e in einst), "Aufflackern wurde eigene Einstellung"
    assert all(tr.positionen(e)[0][0] == pytest.approx(300, abs=80) for e in einst)


def test_positionen_werden_nicht_ueber_den_schnitt_vermischt():
    """Der eigentliche Fehler: 300 und 1500 ergaben gemittelt 900, also niemanden."""
    a = [abt(i * 0.2, [box(300)], 0.02) for i in range(10)]
    a[0].bildwechsel = None
    b = [abt(2.0 + i * 0.2, [box(1500)], 0.02) for i in range(10)]
    b[0].bildwechsel = 0.9
    einst = tr.in_einstellungen_teilen([*a, *b])

    p0 = tr.positionen(einst[0])
    p1 = tr.positionen(einst[1])
    assert p0[0][0] == pytest.approx(300, abs=5)
    assert p1[0][0] == pytest.approx(1500, abs=5)
    # Ohne Trennung waere genau das herausgekommen:
    alle = tr.Einstellung(0.0, 4.0, [*a, *b])
    assert tr.positionen(alle, n_max=1)[0][0] == pytest.approx(900, abs=50)


def test_zwei_personen_in_einer_einstellung_bleiben_zwei():
    a = []
    for i in range(20):
        a.append(abt(i * 0.2, [box(400), box(1400)], 0.02))
    a[0].bildwechsel = None
    einst = tr.in_einstellungen_teilen(a)
    p = tr.positionen(einst[0])
    assert len(p) == 2
    assert p[0][0] == pytest.approx(400, abs=20)
    assert p[1][0] == pytest.approx(1400, abs=20)


# -- Wer spricht -----------------------------------------------------------------------------------
def test_bewegter_mund_gewinnt():
    """Zwei Personen im Bild, nur eine bewegt den Mund."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.9, 0.05]) for i in range(10)]
    assert tr.sprecher_box(a) == 0


def test_die_andere_person_gewinnt_wenn_sie_spricht():
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.04, 0.8]) for i in range(10)]
    assert tr.sprecher_box(a) == 1


def test_ohne_deutlichen_unterschied_keine_entscheidung():
    """Geratener Sprecher ist schlimmer als keiner: der Ausschnitt spraenge auf jemanden, der schweigt."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.50, 0.48]) for i in range(10)]
    assert tr.sprecher_box(a) is None


def test_eine_person_braucht_keinen_vergleich():
    a = [abt(i * 0.2, [box(900)], 0.02, mund=[0.3]) for i in range(10)]
    assert tr.sprecher_box(a) == 0


def test_ohne_bewegung_keine_entscheidung():
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.0, 0.0]) for i in range(10)]
    assert tr.sprecher_box(a) is None


def test_kurzes_zucken_schlaegt_dauerhaftes_sprechen_nicht():
    """Gemittelt wird, nicht summiert: ein einzelner Ausschlag darf nicht gewinnen."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.6, 0.02]) for i in range(10)]
    a.append(abt(2.2, [box(400), box(1400)], 0.02, mund=[0.0, 5.0]))
    assert tr.sprecher_box(a) == 0


# -- Drittelregel ----------------------------------------------------------------------------------
def test_links_sitzende_person_bekommt_blickraum_nach_rechts():
    assert tr.blickraum_anker(400, 1920) == pytest.approx(1 / 3)


def test_rechts_sitzende_person_bekommt_blickraum_nach_links():
    assert tr.blickraum_anker(1500, 1920) == pytest.approx(2 / 3)


def test_mittige_person_bleibt_mittig():
    assert tr.blickraum_anker(960, 1920) == 0.5


def test_knapp_neben_der_mitte_bleibt_mittig():
    """Sonst kippt der Ausschnitt bei jeder kleinen Bewegung hin und her."""
    assert tr.blickraum_anker(1000, 1920) == 0.5


def test_ohne_breite_keine_entscheidung():
    assert tr.blickraum_anker(400, 0) == 0.5
