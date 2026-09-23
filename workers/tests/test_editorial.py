"""Tests für die redaktionelle Grundlage (chopstr_worker/editorial.py).

Die Datei entscheidet, was ein guter Clip ist. Ein Fehler darin ist besonders tückisch, weil das
Ergebnis trotzdem plausibel aussieht: Es kommen Clips heraus, nur die falschen. Deshalb prüfen
diese Tests vor allem, dass eine kaputte Grundlage LAUT scheitert statt still zu wirken.
"""

from __future__ import annotations

import textwrap

import pytest

from chopstr_worker import editorial


@pytest.fixture
def policy():
    editorial.load.cache_clear()
    return editorial.load()


# -- Laden und Prüfen ------------------------------------------------------------------------------
def test_grundlage_laedt_und_ist_vollstaendig(policy):
    assert policy.version == editorial.POLICY_VERSION
    assert editorial.policy_version() == "clip_policy_v1"
    assert policy.stand


def test_gewichte_der_rubrik_ergeben_eins(policy):
    assert sum(policy.gewichte.values()) == pytest.approx(1.0, abs=0.01)


def test_alle_sieben_kriterien_aus_dem_masterfile_sind_da(policy):
    erwartet = {"standalone", "hook", "offene_frage", "spezifitaet", "emotion", "aufloesung", "zielgruppe"}
    assert {k.schluessel for k in policy.kriterien} == erwartet


def test_jedes_kriterium_nennt_seine_herkunft(policy):
    """Ohne Herkunft weiss in drei Monaten niemand mehr, warum eine Regel so dasteht."""
    for k in policy.kriterien:
        assert k.herkunft, f"{k.schluessel} hat keine Herkunftsangabe"


def test_fehlende_datei_scheitert_laut(tmp_path, monkeypatch):
    editorial.load.cache_clear()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    with pytest.raises(editorial.PolicyError, match="nicht gefunden"):
        editorial.load()
    editorial.load.cache_clear()


def test_falsche_gewichtssumme_scheitert_laut(tmp_path, monkeypatch):
    """Gewichte, die nicht auf 1 kommen, verschieben die Rangfolge unbemerkt."""
    (tmp_path / "clip_policy_v1.yaml").write_text(
        textwrap.dedent("""
            version: 1
            laenge: {ziel_s: 41, gut_von_s: 30, gut_bis_s: 55, hart_min_s: 18, hart_max_s: 70}
            rubrik:
              skala_max: 2
              kriterien:
                - {schluessel: hook, frage: x, gewicht: 0.5}
                - {schluessel: payoff, frage: y, gewicht: 0.2}
            bewertung: {modus: sortieren, schwelle_schneiden: 10, schwelle_verwerfen: 7, punkte_gesamt: 14}
            moment_typen: []
            einstieg: {}
            ausstieg: {}
            zusammenhang: {}
            audio: {}
            hook_vorziehen: {}
            ausschluss: {}
        """),
        encoding="utf-8",
    )
    editorial.load.cache_clear()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    with pytest.raises(editorial.PolicyError, match="0.70 statt 1,00"):
        editorial.load()
    editorial.load.cache_clear()


def test_verdrehte_laengengrenzen_scheitern_laut(tmp_path, monkeypatch):
    (tmp_path / "clip_policy_v1.yaml").write_text(
        textwrap.dedent("""
            version: 1
            laenge: {ziel_s: 41, gut_von_s: 55, gut_bis_s: 30, hart_min_s: 18, hart_max_s: 70}
            rubrik:
              skala_max: 2
              kriterien:
                - {schluessel: hook, frage: x, gewicht: 1.0}
            bewertung: {modus: sortieren, schwelle_schneiden: 10, schwelle_verwerfen: 7, punkte_gesamt: 14}
            moment_typen: []
            einstieg: {}
            ausstieg: {}
            zusammenhang: {}
            audio: {}
            hook_vorziehen: {}
            ausschluss: {}
        """),
        encoding="utf-8",
    )
    editorial.load.cache_clear()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    with pytest.raises(editorial.PolicyError, match="aufsteigender Reihenfolge"):
        editorial.load()
    editorial.load.cache_clear()


# -- Länge -----------------------------------------------------------------------------------------
def test_gutes_fenster_bekommt_keinen_abzug(policy):
    for s in (30, 41, 55):
        assert policy.laenge_abzug(s) == 0.0
        assert policy.laenge_ok(s) is True


def test_unsere_heutige_laenge_bekommt_starken_abzug(policy):
    """19,3 s war der gemessene Median unserer Pipeline. Genau das soll auffallen."""
    assert policy.laenge_abzug(19.3) > 0.8
    assert policy.laenge_ok(19.3) is False


def test_die_beiden_ausreisser_aus_dem_material_bekommen_vollen_abzug(policy):
    """124 s und 277 s sind die beiden schlechtesten Beispiele der Redaktion."""
    assert policy.laenge_abzug(124.2) == 1.0
    assert policy.laenge_abzug(277.3) == 1.0


def test_abzug_waechst_stetig(policy):
    werte = [policy.laenge_abzug(s) for s in (56, 60, 65, 70, 80)]
    assert werte == sorted(werte)


# -- Moment-Typen ----------------------------------------------------------------------------------
def test_widerspruch_wird_erkannt(policy):
    assert "contrarian" in policy.typen_im_text("Alle sagen, man müsse früh aufstehen. Das ist falsch.")


def test_zahl_wird_erkannt(policy):
    assert "zahl" in policy.typen_im_text("Wir haben damals 40.000 Euro verloren.")


def test_ministory_wird_erkannt(policy):
    assert "ministory" in policy.typen_im_text("Ich dachte, das läuft. Und dann kam die Rechnung.")


def test_konflikt_braucht_audio_und_wird_im_text_nicht_gemeldet(policy):
    """Der Typ Konflikt hängt laut Masterfile an der lauter werdenden Stimme.

    Ohne Audiosignal darf er nicht aus dem Text allein behauptet werden.
    """
    typen = policy.typen_im_text("Nein, das sehe ich anders. Quatsch.")
    assert "konflikt" not in typen


def test_harmloser_satz_trifft_keinen_typ(policy):
    assert policy.typen_im_text("Wir sprechen heute über das Wetter.") == []


# -- Gesamtwert ------------------------------------------------------------------------------------
def test_volle_punktzahl_ergibt_die_gesamtpunktzahl(policy):
    voll = {k.schluessel: policy.skala_max for k in policy.kriterien}
    assert policy.gesamtwert(voll) == pytest.approx(policy.punkte_gesamt)


def test_null_punkte_ergeben_null(policy):
    assert policy.gesamtwert({k.schluessel: 0 for k in policy.kriterien}) == 0.0


def test_fehlendes_kriterium_zaehlt_als_null(policy):
    """Ein nicht bewertetes Kriterium ist kein erfülltes."""
    nur_hook = policy.gesamtwert({"hook": policy.skala_max})
    voll = policy.gesamtwert({k.schluessel: policy.skala_max for k in policy.kriterien})
    assert 0 < nur_hook < voll


# -- Ausschluss ------------------------------------------------------------------------------------
def test_organisatorisches_gespraech_wird_erkannt(policy):
    """Aus dem Material: „Wo liegt das ungefähr? Eine Stunde von Göteborg entfernt.\""""
    assert policy.ist_organisatorisch("Wo liegt das ungefähr? Eine Stunde von Göteborg entfernt.") is True


def test_inhaltlicher_satz_ist_nicht_organisatorisch(policy):
    assert policy.ist_organisatorisch("Krankschreibungen werden in Deutschland massiv missbraucht.") is False


# -- Prompt ----------------------------------------------------------------------------------------
def test_prompttext_enthaelt_die_regeln_aber_nicht_die_begruendungen(policy):
    text = policy.als_prompt_text()
    assert "RUBRIK" in text and "EINSTIEG" in text and "AUSSTIEG" in text
    for k in policy.kriterien:
        assert k.schluessel in text
    # Herkunftskürzel gehören in die Datei, nicht ins Modell
    assert "[M]" not in text and "[E]" not in text and "[R]" not in text


def test_entscheidung_sortieren_statt_sperren_ist_wirksam(policy):
    """Entscheidung vom 24.09.2026: kein Moment wird unterdrückt, nur sortiert."""
    assert policy.modus == "sortieren"
    assert policy.sperrt is False


# -- Wirkung auf die Rangfolge ---------------------------------------------------------------------
def test_laengenabzug_entscheidet_zwischen_gleichwertigen_momenten(policy):
    """Der Kern der Umstellung: zwei inhaltlich gleiche Momente, nur die Laenge unterscheidet sie.

    Vor der Grundlage wirkte die Laenge gar nicht auf den Gesamtwert. Genau deshalb lieferte die
    Pipeline 19,3 s im Median, waehrend 105 gute Beispielclips bei 41,3 s liegen.
    """
    from chopstr_worker.pipeline import story_engine

    punkte = {k.schluessel: policy.skala_max for k in policy.kriterien}
    r = {"rubric_points": punkte}

    im_fenster = story_engine.policy_total(r, 41.0)
    zu_kurz = story_engine.policy_total(r, 19.3)
    zu_lang = story_engine.policy_total(r, 124.2)

    assert im_fenster > zu_kurz, "Ein Moment im guten Fenster muss einen zu kurzen schlagen"
    assert im_fenster > zu_lang, "Ein Moment im guten Fenster muss einen zu langen schlagen"
    assert im_fenster == pytest.approx(policy.punkte_gesamt)
    assert zu_lang == 0.0, "124 s war das zweitschlechteste Beispiel der Redaktion"


def test_ohne_bewertung_faellt_der_wert_auf_null(policy):
    """Ein unbewertbarer Moment rutscht nach hinten, nicht zufaellig nach vorn."""
    from chopstr_worker.pipeline import story_engine

    assert story_engine.policy_total({}, 41.0) == 0.0
    assert story_engine.policy_total({"rubric_points": {}}, 41.0) == 0.0
