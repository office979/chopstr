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
    # Zwei Schutzschichten greifen hier. Die Trennung an Kameraschnitten haelt die Einstellungen
    # auseinander, und selbst wenn man sie zusammenwirft, trennt die Lueckenclusterung noch immer
    # sauber in zwei Positionen statt eine erfundene Mitte zu bilden. Frueher kam an dieser Stelle
    # 900 heraus, also eine Position, an der niemand sitzt.
    alle = tr.positionen(tr.Einstellung(0.0, 4.0, [*a, *b]))
    assert len(alle) == 2
    assert [round(x) for x, _y in alle] == [300, 1500]


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
POS2 = [(400.0, 400.0), (1400.0, 400.0)]


def test_bewegter_mund_gewinnt():
    """Zwei Personen im Bild, nur eine bewegt den Mund."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.9, 0.05]) for i in range(10)]
    assert tr.sprecher_position(a, POS2) == 0


def test_die_andere_person_gewinnt_wenn_sie_spricht():
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.04, 0.8]) for i in range(10)]
    assert tr.sprecher_position(a, POS2) == 1


def test_wechselnde_reihenfolge_der_erkennung_stoert_nicht():
    """Der Detektor liefert die Gesichter je Bild in wechselnder Reihenfolge.

    An einem echten Video gemessen: t=76.0 x=[1304, 2595], t=76.2 x=[2596, 1305]. Wer ueber den
    Listenindex summiert, vermischt zwei Menschen und bekommt fuer beide denselben Wert. Die erste
    Fassung ist genau daran gescheitert, und kein erdachter Test konnte es zeigen, weil dort die
    Reihenfolge feststeht.
    """
    a = []
    for i in range(10):
        if i % 2:
            a.append(abt(i * 0.2, [box(1400), box(400)], 0.02, mund=[0.9, 0.05]))   # gekippt
        else:
            a.append(abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.05, 0.9]))
    # In beiden Faellen spricht die Person bei x=1400.
    assert tr.sprecher_position(a, POS2) == 1


def test_ohne_deutlichen_unterschied_keine_entscheidung():
    """Geratener Sprecher ist schlimmer als keiner: der Ausschnitt spraenge auf jemanden, der schweigt."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.50, 0.48]) for i in range(10)]
    assert tr.sprecher_position(a, POS2) is None


def test_eine_person_braucht_keinen_vergleich():
    a = [abt(i * 0.2, [box(900)], 0.02, mund=[0.3]) for i in range(10)]
    assert tr.sprecher_position(a, [(900.0, 400.0)]) == 0


def test_ohne_bewegung_keine_entscheidung():
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.0, 0.0]) for i in range(10)]
    assert tr.sprecher_position(a, POS2) is None


def test_kurzes_zucken_schlaegt_dauerhaftes_sprechen_nicht():
    """Median statt Mittelwert: ein einzelner Ausschlag darf nicht gewinnen."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.6, 0.02]) for i in range(10)]
    a.append(abt(2.2, [box(400), box(1400)], 0.02, mund=[0.0, 5.0]))
    assert tr.sprecher_position(a, POS2) == 0


def test_echte_werte_aus_dem_testvideo():
    """Gemessen an BP CW zwischen 76 und 79 Sekunden, drei Personen im Bild.

    Die Person bei x rund 2580 hatte 13 bis 33, die bei 1305 nur 1,8 bis 2,2.
    """
    pos = [(1305.0, 700.0), (2580.0, 700.0), (2980.0, 700.0)]
    roh = [
        ([1305, 2593], [1.91, 21.34]),
        ([1305, 2583], [2.23, 33.67]),
        ([1307, 2586], [1.92, 28.72]),
        ([2591, 1306, 2981], [19.21, 1.8, 3.72]),   # Reihenfolge gekippt, wie im Original
        ([1306, 2577, 2984], [2.21, 21.82, 3.48]),
        ([1305, 2571], [2.17, 13.46]),
    ]
    a = [abt(76.0 + i * 0.2, [box(x) for x in xs], 0.02, mund=m) for i, (xs, m) in enumerate(roh)]
    assert tr.sprecher_position(a, pos) == 1


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


def test_eine_person_wird_nicht_in_drei_positionen_zersaegt():
    """Gemessen an BP CW: eine Person ergab frueher die Positionen 1126, 2147 und 3234.

    Ursache war eine erzwungene Clusterzahl. Bei stetigen x-Werten war sie praktisch immer das
    Hoechstmass, und k-Means zerlegte eine einzelne Haeufung in drei Teile.
    """
    a = []
    for i in range(60):
        wackel = (i % 7) - 3  # leichte Kopfbewegung, wie im echten Video
        a.append(abt(i * 0.2, [box(1900 + wackel * 12)], 0.02))
    a[0].bildwechsel = None
    p = tr.positionen(tr.in_einstellungen_teilen(a)[0])
    assert len(p) == 1, f"Eine Person, aber {len(p)} Positionen: {[round(x) for x, _ in p]}"
    assert p[0][0] == pytest.approx(1900, abs=60)


def test_vereinzelte_fehlerkennung_wird_verworfen():
    """Ein Poster oder eine Spiegelung darf keine Sitzposition werden."""
    a = [abt(i * 0.2, [box(1900)], 0.02) for i in range(60)]
    a[0].bildwechsel = None
    a[10].boxen.append(box(200))  # zwei Ausreisser
    a[30].boxen.append(box(200))
    p = tr.positionen(tr.in_einstellungen_teilen(a)[0])
    assert len(p) == 1
    assert p[0][0] == pytest.approx(1900, abs=60)


def test_kaum_sichtbare_erkennung_gewinnt_nicht():
    """An BP CW gemessen: eine Erkennung mit 5 Messungen schlug den echten Sprecher mit 32,
    allein weil ihr Median hoeher lag. Ueber jemanden, der kaum sichtbar ist, laesst sich nicht
    urteilen."""
    pos = [(1306.0, 700.0), (1953.0, 700.0), (2576.0, 700.0)]
    a = []
    for i in range(40):
        boxen = [box(1306), box(2576)]
        mund = [2.0, 18.9]
        if i % 8 == 0:           # nur in jedem achten Bild sichtbar
            boxen.append(box(1953))
            mund.append(21.2)    # hoeherer Median, aber kaum Rueckhalt
        a.append(abt(i * 0.2, boxen, 0.02, mund=mund))
    assert tr.sprecher_position(a, pos) == 2


def test_nicht_messbare_werte_zaehlen_nicht_als_ruhe():
    """NICHT_MESSBAR heisst keine Aussage. Als 0 gewertet wuerde es einen Sprecher verwaessern."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[tr.NICHT_MESSBAR, 0.9]) for i in range(10)]
    assert tr.sprecher_position(a, POS2) == 1


def test_runde_mit_sieben_personen_wird_nicht_auf_drei_gekuerzt():
    """An BP CW gemessen: sieben Personen an einem Tisch, alle sicher erkannt.

    Mit der alten Grenze von drei Positionen fielen vier davon weg, und der Sprecher war
    womoeglich gar nicht unter den dreien.
    """
    xs = [713, 1103, 1396, 2056, 2425, 3038, 3484]
    a = [abt(i * 0.2, [box(x) for x in xs], 0.02, mund=[1.0] * len(xs)) for i in range(40)]
    a[0].bildwechsel = None
    p = tr.positionen(tr.in_einstellungen_teilen(a)[0])
    assert len(p) == 7
    assert [round(x) for x, _y in p] == xs

# -- Was wann im Bild steht ------------------------------------------------------------------------
def _einstellungen(abtastungen):
    return tr.in_einstellungen_teilen(abtastungen)


def test_eine_person_ergibt_ein_ziel_ueber_die_ganze_einstellung():
    a = [abt(i * 0.2, [box(500)], 0.02) for i in range(20)]
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920)
    assert len(z) == 1
    assert z[0].grund == "einzige_person"
    assert z[0].cx == pytest.approx(500, abs=20)
    # Links der Mitte: Blickraum nach rechts, also sitzt das Gesicht auf dem linken Drittel.
    assert z[0].anker == pytest.approx(1 / 3)


def test_kamerawechsel_ergibt_zwei_ziele():
    """Der Kern der Sache: ueber den Schnitt hinweg bedeutet dieselbe Bildstelle einen anderen Menschen."""
    a = [abt(i * 0.2, [box(300)], 0.02) for i in range(10)]
    a[0].bildwechsel = None
    b = [abt(2.0 + i * 0.2, [box(1500)], 0.02) for i in range(10)]
    b[0].bildwechsel = 0.9
    z = tr.ziele(_einstellungen([*a, *b]), 1920)
    assert len(z) == 2
    assert z[0].cx == pytest.approx(300, abs=20) and z[1].cx == pytest.approx(1500, abs=20)
    assert z[0].ende_s <= z[1].start_s
    # Und die Drittelregel dreht mit: links sitzend nach rechts, rechts sitzend nach links.
    assert z[0].anker == pytest.approx(1 / 3) and z[1].anker == pytest.approx(2 / 3)


def test_sprecherwechsel_innerhalb_einer_einstellung():
    a = []
    for i in range(20):
        mund = [0.9, 0.05] if i < 10 else [0.05, 0.9]
        a.append(abt(i * 0.2, [box(400), box(1400)], 0.02, mund=mund))
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920)
    assert len(z) == 2, [(x.start_s, x.ende_s, x.cx) for x in z]
    assert z[0].cx == pytest.approx(400, abs=20)
    assert z[1].cx == pytest.approx(1400, abs=20)
    assert all(x.grund == "sprecher" for x in z)


def test_kurzer_wechsel_laesst_das_bild_stehen():
    """Ein Ausschnitt, der eine halbe Sekunde steht, wirkt wie ein Fehler, auch wenn die Erkennung recht hat."""
    a = []
    for i in range(20):
        mund = [0.05, 0.9] if i in (8, 9) else [0.9, 0.05]  # 0,4 s Zwischenruf
        a.append(abt(i * 0.2, [box(400), box(1400)], 0.02, mund=mund))
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920, fenster_s=0.4)
    assert len(z) == 1
    assert z[0].cx == pytest.approx(400, abs=20)
    assert all(x.dauer_s >= tr.MIN_ZIEL_S for x in z)


def test_kurze_pause_ist_kein_sprecherwechsel():
    """Wer kurz Luft holt, darf nicht aus dem Bild fallen."""
    a = []
    for i in range(20):
        mund = [0.0, 0.0] if 8 <= i < 12 else [0.9, 0.05]
        a.append(abt(i * 0.2, [box(400), box(1400)], 0.02, mund=mund))
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920)
    assert len(z) == 1 and z[0].cx == pytest.approx(400, abs=20)


def test_ohne_erkennbaren_sprecher_bleibt_die_gruppe_im_bild():
    """Geraten waere schlimmer: dann stuende jemand gross im Bild, der gerade schweigt."""
    a = [abt(i * 0.2, [box(400), box(1400)], 0.02, mund=[0.5, 0.48]) for i in range(20)]
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920)
    assert len(z) == 1
    assert z[0].grund == "gruppe_unentschieden"
    assert z[0].cx == pytest.approx(900, abs=30)  # die Mitte zwischen beiden
    assert z[0].anker == 0.5


def test_ohne_folgen_bleibt_die_haeufigste_person_im_bild():
    """Strategie talking_head: Kameraschnitte zaehlen weiter, aber innerhalb einer Einstellung steht das Bild."""
    a = []
    for i in range(20):
        boxen = [box(400), box(1400)] if i % 2 else [box(400)]
        mund = [0.05, 0.9] if i % 2 else [0.05]
        a.append(abt(i * 0.2, boxen, 0.02, mund=mund))
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920, folgen=False)
    assert len(z) == 1
    assert z[0].grund == "haeufigste_person"
    assert z[0].cx == pytest.approx(400, abs=20)


def test_ohne_gesicht_bleibt_es_mittig():
    a = [abt(i * 0.2, [], 0.02) for i in range(10)]
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920)
    assert len(z) == 1 and z[0].cx is None and z[0].grund == "kein_gesicht" and z[0].anker == 0.5


def test_ziele_haben_keine_luecken_und_keine_ueberlappung():
    a = []
    for i in range(30):
        mund = [0.9, 0.05] if i < 15 else [0.05, 0.9]
        a.append(abt(i * 0.2, [box(400), box(1400)], 0.02, mund=mund))
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 1920)
    for vor, nach in zip(z, z[1:]):
        assert vor.ende_s == pytest.approx(nach.start_s)


# -- Blickraum aus dem Kontext ---------------------------------------------------------------------
def test_sprecher_mit_leuten_rechts_von_sich_bekommt_blickraum_nach_rechts():
    assert tr.blickraum_anker(1000, 3840, andere=[2000, 2600]) == pytest.approx(1 / 3)


def test_sprecher_mit_leuten_links_von_sich_bekommt_blickraum_nach_links():
    assert tr.blickraum_anker(2600, 3840, andere=[700, 1300]) == pytest.approx(2 / 3)


def test_sprecher_mitten_in_der_gruppe_bleibt_mittig():
    """Der Fehler aus der Praxis: links der Bildmitte, aber mit drei Leuten links von sich."""
    assert tr.blickraum_anker(1100, 3840, andere=[700, 1400, 2100, 2400, 3000]) == 0.5


def test_ohne_andere_entscheidet_die_lage_im_bild():
    assert tr.blickraum_anker(700, 3840) == pytest.approx(1 / 3)
    assert tr.blickraum_anker(3100, 3840) == pytest.approx(2 / 3)


def test_gruppenaufnahme_schiebt_den_ausschnitt_nicht_von_der_gruppe_weg():
    """Sieben Personen, der Sprecher sitzt links der Bildmitte, aber nicht am Rand der Gruppe."""
    xs = [700, 1100, 1400, 2100, 2400, 3000, 3400]
    a = []
    for i in range(20):
        mund = [0.05] * len(xs)
        mund[1] = 0.9  # der bei 1100 spricht
        a.append(abt(i * 0.2, [box(x, b=140) for x in xs], 0.02, mund=mund))
    a[0].bildwechsel = None
    z = tr.ziele(_einstellungen(a), 3840)
    assert len(z) == 1
    assert z[0].cx == pytest.approx(1100, abs=30)
    assert z[0].anker == 0.5, "Anker zieht den Ausschnitt aus der Gruppe heraus"


# -- Ruhe ueber Schnitte hinweg --------------------------------------------------------------------
def _einstellung_mit(start, cx, n=15, breite=400):
    a = [abt(start + i * 0.2, [box(cx, b=breite)], 0.02) for i in range(n)]
    a[0].bildwechsel = 0.9
    return a


def test_derselbe_mensch_nach_einem_schnitt_behaelt_seinen_ausschnitt():
    """Gemessen an BP CW: 2062, 1924, 2152 - dreimal dieselbe Person, dreimal ein anderer Ausschnitt."""
    a = _einstellung_mit(0.0, 2062)
    a[0].bildwechsel = None
    b = _einstellung_mit(3.0, 1924)
    c = _einstellung_mit(6.0, 2152)
    z = tr.ziele(_einstellungen([*a, *b, *c]), 3840)
    assert len(z) == 3, "die Einstellungen sollen getrennt bleiben"
    assert len({round(q.cx) for q in z}) == 1, [round(q.cx) for q in z]


def test_ein_echter_wechsel_wird_nicht_wegberuhigt():
    a = _einstellung_mit(0.0, 1300)
    a[0].bildwechsel = None
    b = _einstellung_mit(3.0, 2580)
    z = tr.ziele(_einstellungen([*a, *b]), 3840)
    assert [round(q.cx) for q in z] == [1300, 2580]


def test_in_der_totale_gilt_ein_kleinerer_massstab():
    """Kleine Gesichter heisst: zweihundert Punkte sind zwei Personen, nicht ein halbes Gesicht."""
    a = _einstellung_mit(0.0, 1000, breite=120)
    a[0].bildwechsel = None
    b = _einstellung_mit(3.0, 1200, breite=120)
    z = tr.ziele(_einstellungen([*a, *b]), 3840)
    assert [round(q.cx) for q in z] == [1000, 1200]


# -- Zeitmarken von Hand ---------------------------------------------------------------------------
def _ziel(a, b, cx, auswahl=(), grund="sprecher"):
    return tr.Ziel(start_s=a, ende_s=b, cx=cx, cy=400.0, anker=0.5, grund=grund, breite=200.0, auswahl=list(auswahl))


def test_ohne_marken_bleibt_alles_wie_es_war():
    z = [_ziel(0.0, 10.0, 400.0, [400.0, 1400.0])]
    assert tr.zeitmarken_anwenden(z, [], 1920) is z


def test_eine_marke_setzt_die_person_ab_ihrer_sekunde():
    z = [_ziel(0.0, 10.0, 400.0, [400.0, 1400.0])]
    aus = tr.zeitmarken_anwenden(z, [{"ab_s": 4.0, "x": 1400.0}], 1920)
    assert [(round(x.start_s, 1), round(x.ende_s, 1), x.cx) for x in aus] == [(0.0, 4.0, 400.0), (4.0, 10.0, 1400.0)]
    assert aus[1].grund == "von_hand"


def test_eine_marke_wirkt_nicht_erst_beim_naechsten_schnitt():
    """Ohne das Trennen mitten im Ziel wuerde eine Marke bei 4 s erst bei 10 s greifen."""
    aus = tr.zeitmarken_anwenden([_ziel(0.0, 10.0, 400.0, [400.0, 1400.0])], [{"ab_s": 4.0, "x": 1400.0}], 1920)
    assert len(aus) == 2 and aus[1].start_s == 4.0


def test_die_marke_rastet_auf_die_naechste_erkannte_person_ein():
    """Nach einer neuen Erkennung liegt die Person ein paar Punkte anders. Die Marke muss mit."""
    aus = tr.zeitmarken_anwenden([_ziel(0.0, 10.0, 400.0, [402.0, 1396.0])], [{"ab_s": 0.0, "x": 1400.0}], 1920)
    assert aus[0].cx == 1396.0


def test_ohne_erkannte_person_gilt_die_bildstelle_der_marke():
    aus = tr.zeitmarken_anwenden([_ziel(0.0, 10.0, None, [])], [{"ab_s": 0.0, "x": 900.0}], 1920)
    assert aus[0].cx == 900.0


def test_die_marke_schlaegt_die_automatik():
    """Wer von Hand entscheidet, will nicht ueberstimmt werden."""
    aus = tr.zeitmarken_anwenden([_ziel(0.0, 10.0, 400.0, [400.0, 1400.0], grund="sprecher")], [{"ab_s": 0.0, "x": 1400.0}], 1920)
    assert aus[0].cx == 1400.0 and aus[0].grund == "von_hand"


def test_mehrere_marken_loesen_sich_der_reihe_nach_ab():
    z = [_ziel(0.0, 12.0, 400.0, [400.0, 900.0, 1400.0])]
    aus = tr.zeitmarken_anwenden(z, [{"ab_s": 8.0, "x": 900.0}, {"ab_s": 4.0, "x": 1400.0}], 1920)
    assert [(round(x.start_s, 1), x.cx) for x in aus] == [(0.0, 400.0), (4.0, 1400.0), (8.0, 900.0)]


def test_eine_marke_wirkt_ueber_mehrere_einstellungen_hinweg():
    z = [_ziel(0.0, 5.0, 400.0, [400.0, 1400.0]), _ziel(5.0, 10.0, 400.0, [400.0, 1400.0])]
    aus = tr.zeitmarken_anwenden(z, [{"ab_s": 2.0, "x": 1400.0}], 1920)
    assert all(x.cx == 1400.0 for x in aus if x.start_s >= 2.0)


def test_unbrauchbare_marken_werden_uebergangen():
    z = [_ziel(0.0, 10.0, 400.0, [400.0, 1400.0])]
    aus = tr.zeitmarken_anwenden(z, [{"ab_s": None, "x": 1400.0}, {"x": 900.0}, {"ab_s": 3.0}], 1920)
    assert len(aus) == 1 and aus[0].cx == 400.0


def test_die_drittelregel_gilt_auch_fuer_eine_marke():
    """Wird von Hand die rechte Person gewaehlt, gehoert der Blickraum nach links."""
    aus = tr.zeitmarken_anwenden([_ziel(0.0, 10.0, 400.0, [400.0, 1400.0])], [{"ab_s": 0.0, "x": 1400.0}], 1920)
    assert aus[0].anker == pytest.approx(2 / 3)
