"""Die technische Prüfung der fertigen Datei.

Was diese Tests festhalten, ist nicht die Messung - die gab es schon - sondern die Folge. Vorher
schrieb ``regression_checks`` freie Sätze in eine Notizliste, und darunter stand ``rendered``, egal
was herauskam. Hier steht, wann ein Befund ein Fehler ist und wann nur ein Hinweis, denn genau
daran hängt, ob die Fassung hinausgehen darf.
"""

from __future__ import annotations

import json

from chopstr_worker.pipeline import ausgabe_pruefung as ap


def lauf(**over):
    grund = dict(
        datei_vorhanden=True,
        hat_bild=True,
        hat_ton=True,
        dauer_s=30.0,
        geplante_dauer_s=30.0,
        breite=1080,
        hoehe=1920,
        geplante_breite=1080,
        geplante_hoehe=1920,
        schwarzbilder=[],
        lufs=-16.0,
        ziel_lufs=-16.0,
        spitze_dbtp=-2.0,
        ziel_spitze_dbtp=-1.5,
        woerter=80,
        untertitelkarten=40,
        untertitel_eingebrannt=True,
    )
    grund.update(over)
    return ap.pruefen(**grund)


def ergebnis(befunde, code):
    return next(b.ergebnis for b in befunde if b.pruefung == code)


def test_eine_saubere_datei_besteht_alles():
    b = lauf()
    assert ap.schlimmstes(b) == "ok"
    assert ap.fehlertext(b) is None
    # Auch die bestandenen Pruefungen stehen in der Liste: nur so ist spaeter zu unterscheiden,
    # ob etwas geprueft und in Ordnung war oder gar nicht geprueft wurde.
    assert len(b) == 10


def test_ohne_tonspur_ist_es_ein_fehler():
    b = lauf(hat_ton=False)
    assert ergebnis(b, "ton") == "fehler"
    assert ap.schlimmstes(b) == "fehler"
    assert "stumm" in ap.fehlertext(b)


def test_ohne_bildspur_ist_es_ein_fehler():
    assert ergebnis(lauf(hat_bild=False), "bild") == "fehler"


def test_fehlende_datei_bricht_die_pruefung_ab():
    b = lauf(datei_vorhanden=False)
    # Ein Dutzend Folgefehler wuerde den einen Grund verstecken, auf den es ankommt.
    assert len(b) == 1 and b[0].pruefung == "datei"


def test_laenge_kleine_abweichung_ist_ein_hinweis_grosse_ein_fehler():
    assert ergebnis(lauf(dauer_s=30.1), "dauer") == "ok"
    assert ergebnis(lauf(dauer_s=30.5), "dauer") == "hinweis"
    assert ergebnis(lauf(dauer_s=31.5), "dauer") == "fehler"


def test_andere_bildgroesse_ist_ein_fehler():
    b = lauf(breite=1080, hoehe=1080)
    assert ergebnis(b, "aufloesung") == "fehler"
    assert "1080x1080" in next(x.gemessen for x in b if x.pruefung == "aufloesung")


def test_langes_schwarzbild_ist_ein_fehler():
    assert ergebnis(lauf(schwarzbilder=[(2.0, 2.4)]), "schwarzbild") == "ok"
    assert ergebnis(lauf(schwarzbilder=[(2.0, 2.7)]), "schwarzbild") == "hinweis"
    assert ergebnis(lauf(schwarzbilder=[(2.0, 3.5)]), "schwarzbild") == "fehler"


def test_lautstaerke_wird_gegen_den_plan_gemessen():
    # Diese Pruefung gab es vorher ueberhaupt nicht: gemessen wurde, verglichen nie.
    assert ergebnis(lauf(lufs=-17.5), "pegel") == "ok"
    assert ergebnis(lauf(lufs=-18.5), "pegel") == "hinweis"
    assert ergebnis(lauf(lufs=-21.0), "pegel") == "fehler"
    assert ergebnis(lauf(lufs=-10.0), "pegel") == "fehler"


def test_uebersteuerung_wird_erkannt():
    assert ergebnis(lauf(spitze_dbtp=-1.5), "spitze") == "ok"
    assert ergebnis(lauf(spitze_dbtp=-0.8), "spitze") == "hinweis"
    assert ergebnis(lauf(spitze_dbtp=1.0), "spitze") == "fehler"


def test_fehlende_untertitel_sind_ein_fehler_wenn_gesprochen_wird():
    assert ergebnis(lauf(untertitelkarten=0), "untertitel") == "fehler"
    assert ergebnis(lauf(untertitel_eingebrannt=False), "untertitel") == "fehler"


def test_ohne_gesprochene_woerter_sind_fehlende_untertitel_richtig():
    assert ergebnis(lauf(woerter=0, untertitelkarten=0), "untertitel") == "ok"


def test_nicht_eingebrannt_nennt_den_server_als_ursache():
    b = lauf(untertitel_eingebrannt=False)
    text = next(x.text for x in b if x.pruefung == "untertitel")
    # Wer dreimal dasselbe versucht, weil der Satz die Ursache verschweigt, hat nichts gewonnen.
    assert "Server" in text


def test_nicht_messbares_sperrt_nicht():
    b = lauf(lufs=None, ziel_lufs=None, dauer_s=None)
    assert ergebnis(b, "pegel") == "hinweis"
    assert ergebnis(b, "dauer") == "hinweis"
    assert ap.schlimmstes(b) == "hinweis"


def test_die_grenzwerte_kommen_aus_der_gemeinsamen_datei():
    # Dieselbe Datei liest die Web-App. Zwei Stellen mit denselben Zahlen waren der Grund dafuer,
    # dass Oberflaeche und Server verschieden geantwortet haben.
    with open(ap._regeln_pfad(), encoding="utf-8") as f:
        d = json.load(f)
    codes = {p["code"] for p in d["technische_pruefungen"]["pruefungen"]}
    assert {b.pruefung for b in lauf()} == codes


def test_eine_fehlende_schrift_ist_ein_hinweis_und_kein_fehler():
    """Ein Video wegen einer Schrift zu sperren waere unverhaeltnismaessig - aber es
    stillschweigend anders aussehen zu lassen, ist auch keine Loesung."""
    b = lauf(schrift_ersetzt="Schriftdatei Anton.ttf fehlt in /fonts")
    assert ergebnis(b, "schrift") == "hinweis"
    assert ap.schlimmstes(b) == "hinweis"
    assert "nicht aus wie eingestellt" in next(x.text for x in b if x.pruefung == "schrift")


def test_ohne_ersetzung_ist_die_schrift_in_ordnung():
    assert ergebnis(lauf(), "schrift") == "ok"


def test_die_liste_ist_als_json_ablegbar():
    liste = ap.als_liste(lauf(hat_ton=False))
    assert json.loads(json.dumps(liste, ensure_ascii=False))[2]["ergebnis"] == "fehler"
