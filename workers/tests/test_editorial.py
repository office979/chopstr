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
    editorial.clear_cache()
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
    editorial.clear_cache()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    with pytest.raises(editorial.PolicyError, match="nicht gefunden"):
        editorial.load()
    editorial.clear_cache()


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
    editorial.clear_cache()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    with pytest.raises(editorial.PolicyError, match="0.70 statt 1,00"):
        editorial.load()
    editorial.clear_cache()


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
    editorial.clear_cache()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    with pytest.raises(editorial.PolicyError, match="aufsteigender Reihenfolge"):
        editorial.load()
    editorial.clear_cache()


# -- Startprüfung des Workers (AP0a) -------------------------------------------------------------
def test_startup_check_passes_with_repo_files():
    from chopstr_worker import worker

    editorial.clear_cache()
    worker.check_assets()


def test_startup_check_aborts_clearly_when_editorial_dir_is_empty(tmp_path, monkeypatch):
    """Im Image ohne Policy soll der Worker gar nicht erst starten, statt in der Kandidatensuche zu scheitern."""
    from chopstr_worker import worker

    editorial.clear_cache()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path / "gibt_es_nicht"))
    with pytest.raises(SystemExit) as excinfo:
        worker.check_assets()
    editorial.clear_cache()
    message = str(excinfo.value)
    assert message.startswith("Der Worker startet nicht, weil gemeinsame Dateien fehlen")
    assert "Redaktionelle Grundlage (EDITORIAL_DIR)" in message
    assert "nicht gefunden" in message and str(tmp_path / "gibt_es_nicht") in message
    assert "Schriftenliste" not in message and "Ausgaberegeln" not in message
    assert "Gepinnte Prompts" not in message  # derselbe Fehler nicht ein zweites Mal
    assert message.count("nicht gefunden") == 1


def test_startup_check_names_invalid_policy_version_under_its_variable(monkeypatch):
    """Ein Tippfehler im Rollback-Schalter erscheint einmal und unter ``CHOPSTR_POLICY_VERSION``."""
    from chopstr_worker import worker

    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "zwei")
    editorial.clear_cache()
    with pytest.raises(SystemExit) as excinfo:
        worker.check_assets()
    editorial.clear_cache()
    message = str(excinfo.value)
    assert "Fassung der redaktionellen Grundlage (CHOPSTR_POLICY_VERSION): CHOPSTR_POLICY_VERSION='zwei'" in message
    assert "EDITORIAL_DIR" not in message and "PROMPTS_DIR" not in message
    assert message.count("keine Fassungsnummer") == 1


def test_startup_check_names_missing_fonts_and_output_rules(tmp_path, monkeypatch):
    from chopstr_worker import worker
    from chopstr_worker.pipeline import ausgabe_pruefung, captions_de

    monkeypatch.setattr(captions_de, "_fonts_zwischenspeicher", None)
    monkeypatch.setattr(ausgabe_pruefung, "_zwischenspeicher", None)
    monkeypatch.setenv("CHOPSTR_CAPTION_FONTS", str(tmp_path / "caption_fonts.json"))
    monkeypatch.setenv("CHOPSTR_AUSGABE_REGELN", str(tmp_path / "ausgabe_regeln_v1.json"))
    editorial.clear_cache()
    with pytest.raises(SystemExit) as excinfo:
        worker.check_assets()
    message = str(excinfo.value)
    assert "Schriftenliste (CHOPSTR_CAPTION_FONTS)" in message
    assert "Ausgaberegeln (CHOPSTR_AUSGABE_REGELN)" in message
    assert "Redaktionelle Grundlage" not in message


def test_startup_check_rejects_existing_but_invalid_fonts_and_output_rules(tmp_path, monkeypatch):
    """L2: Die Dateien existieren und sind gültiges JSON, aber die Pflichtschlüssel fehlen oder sind leer."""
    from chopstr_worker import worker
    from chopstr_worker.pipeline import ausgabe_pruefung, captions_de

    fonts = tmp_path / "caption_fonts.json"
    fonts.write_text('{"version": "x", "schriften": []}', encoding="utf-8")
    rules = tmp_path / "ausgabe_regeln_v1.json"
    rules.write_text('{"version": "ausgabe_regeln_v1", "technische_pruefungen": {}}', encoding="utf-8")
    monkeypatch.setattr(captions_de, "_fonts_zwischenspeicher", None)
    monkeypatch.setattr(ausgabe_pruefung, "_zwischenspeicher", None)
    monkeypatch.setenv("CHOPSTR_CAPTION_FONTS", str(fonts))
    monkeypatch.setenv("CHOPSTR_AUSGABE_REGELN", str(rules))
    editorial.clear_cache()
    with pytest.raises(SystemExit) as excinfo:
        worker.check_assets()
    message = str(excinfo.value)
    assert "Schriftenliste (CHOPSTR_CAPTION_FONTS): Pflichtschlüssel schriften ist keine nicht leere Liste" in message
    assert "Ausgaberegeln (CHOPSTR_AUSGABE_REGELN): Pflichtschlüssel technische_pruefungen.pruefungen fehlt" in message
    assert "Redaktionelle Grundlage" not in message and "Gepinnte Prompts" not in message


def test_startup_check_loads_every_pinned_prompt(tmp_path, monkeypatch):
    """L1: Fehlt eine gepinnte Prompt-Datei, startet der Worker nicht, statt mitten im Lauf zu scheitern."""
    import shutil

    from chopstr_worker import prompts, worker

    real = prompts.prompts_dir()
    for path in real.glob("*.md"):
        if path.name != "score_clip_v2.md":
            shutil.copy(path, tmp_path / path.name)
    monkeypatch.setenv("PROMPTS_DIR", str(tmp_path))
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "1")
    prompts.clear_cache()
    editorial.clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            worker.check_assets()
    finally:
        prompts.clear_cache()
    message = str(excinfo.value)
    assert "Gepinnte Prompts (PROMPTS_DIR)" in message and "score_clip_v2.md" in message
    assert "Redaktionelle Grundlage" not in message


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


# -- Klanganteil -----------------------------------------------------------------------------------
def _heat(audio_values, bin_s=1.0):
    return {"bin_s": bin_s, "n_bins": len(audio_values), "values": audio_values, "audio_values": audio_values}


def test_ohne_audioanteil_bleibt_der_wert_unberuehrt(policy):
    """Alte Heatmaps haben kein audio_values. Dann wird nichts erfunden."""
    from chopstr_worker.pipeline import story_engine

    assert story_engine.audio_wert(None, 0.0, 10.0) is None
    assert story_engine.audio_wert({"bin_s": 1.0, "values": [1, 2, 3]}, 0.0, 3.0) is None

    r = {"rubric_points": {k.schluessel: policy.skala_max for k in policy.kriterien}}
    assert story_engine.policy_total(r, 41.0, audio=None) == pytest.approx(policy.punkte_gesamt)


def test_lauter_abschnitt_schlaegt_leisen(policy):
    from chopstr_worker.pipeline import story_engine

    leise = story_engine.audio_wert(_heat([-2.0] * 40), 0.0, 40.0)
    laut = story_engine.audio_wert(_heat([2.0] * 40), 0.0, 40.0)
    assert laut > leise


def test_lauter_werdende_stimme_schlaegt_gleichbleibende(policy):
    """Die Masterclass nennt beim Typ Konflikt ausdruecklich die lauter werdende Stimme."""
    from chopstr_worker.pipeline import story_engine

    gleich = story_engine.audio_wert(_heat([0.0] * 40), 0.0, 40.0)
    steigend = story_engine.audio_wert(_heat([-1.0] * 20 + [1.0] * 20), 0.0, 40.0)
    assert steigend > gleich


def test_durchschnittlicher_klang_veraendert_den_wert_nicht(policy):
    """0,5 ist neutral. Sonst wuerde jeder Clip allein durch das Anschliessen des Audios abgewertet."""
    from chopstr_worker.pipeline import story_engine

    r = {"rubric_points": {k.schluessel: policy.skala_max for k in policy.kriterien}}
    ohne = story_engine.policy_total(r, 41.0, audio=None)
    neutral = story_engine.policy_total(r, 41.0, audio=0.5)
    assert neutral == pytest.approx(ohne)


def test_klang_wirkt_in_beide_richtungen(policy):
    from chopstr_worker.pipeline import story_engine

    r = {"rubric_points": {k.schluessel: policy.skala_max for k in policy.kriterien}}
    neutral = story_engine.policy_total(r, 41.0, audio=0.5)
    hoch = story_engine.policy_total(r, 41.0, audio=1.0)
    tief = story_engine.policy_total(r, 41.0, audio=0.0)
    w = float(policy.audio["gewicht"])
    assert hoch == pytest.approx(neutral * (1 + w), abs=0.02)
    assert tief == pytest.approx(neutral * (1 - w), abs=0.02)


# -- Hook vorziehen --------------------------------------------------------------------------------
def _sents(texte, ab=0.0, laenge=3.0):
    from chopstr_worker.pipeline.segment import Sentence

    out, t = [], ab
    for i, x in enumerate(texte):
        out.append(Sentence(idx=i, text=x, start=t, end=t + laenge, speaker="S0", word_range=(i, i)))
        t += laenge
    return out


def test_teaserlaenge_stimmt_mit_dem_zusammensetzen_ueberein(policy):
    """Die Grundlage darf keinen Teaser erlauben, den compose.validate danach ablehnt."""
    from chopstr_worker.pipeline import compose

    assert float(policy.hook_vorziehen["max_teaser_s"]) == pytest.approx(compose.MAX_TEASER_S)


def test_starker_satz_aus_der_mitte_wird_vorgezogen(policy):
    from chopstr_worker.pipeline import story_engine

    s = _sents([
        "Wir haben lange darueber nachgedacht wie man das angehen koennte.",
        "Alle sagen man muesse frueh aufstehen. Das ist falsch.",
        "Deswegen haben wir es anders gemacht.",
        "Am Ende kam etwas Brauchbares heraus.",
    ])
    assert story_engine.teaser_satz(s, 0, 3, policy, None) == 1


def test_satz_mit_rueckverweis_wird_nie_teaser(policy):
    """Vorgezogen haette er nichts, worauf er sich bezieht."""
    from chopstr_worker.pipeline import story_engine

    s = _sents([
        "Wir haben lange darueber nachgedacht wie man das angehen koennte.",
        "Deswegen haben wir 40 Prozent eingespart und alle sagen das ist falsch.",
        "Am Ende kam etwas Brauchbares heraus.",
        "Und so blieb es dann auch.",
    ])
    assert story_engine.satz_staerke(s[1], policy, None) == -1.0
    assert story_engine.teaser_satz(s, 0, 3, policy, None) != 1


def test_ohne_deutlichen_vorsprung_bleibt_die_reihenfolge(policy):
    from chopstr_worker.pipeline import story_engine

    s = _sents(["Ein ruhiger Satz.", "Noch ein ruhiger Satz.", "Und ein dritter.", "Und ein vierter."])
    assert story_engine.teaser_satz(s, 0, 3, policy, None) is None


def test_aus_dem_letzten_teil_wird_nichts_vorgezogen(policy):
    """Sonst nimmt der Teaser die Aufloesung vorweg."""
    from chopstr_worker.pipeline import story_engine

    s = _sents([
        "Wir haben lange darueber nachgedacht.",
        "Ein ruhiger Satz.",
        "Noch ein ruhiger Satz.",
        "Alle sagen das ist falsch und in wahrheit ist es ganz anders.",
    ])
    assert story_engine.teaser_satz(s, 0, 3, policy, None) is None


def test_zu_kurze_spanne_bekommt_keinen_teaser(policy):
    from chopstr_worker.pipeline import story_engine

    s = _sents(["Alle sagen das ist falsch.", "Und dann kam es anders."])
    assert story_engine.teaser_satz(s, 0, 1, policy, None) is None


# -- Fassungen und Pins (AP0b) ---------------------------------------------------------------------
@pytest.fixture
def v2_raw():
    import yaml

    return yaml.safe_load((editorial.policy_dir() / "clip_policy_v2.yaml").read_text(encoding="utf-8"))


def _write_v2(tmp_path, monkeypatch, data):
    import yaml

    (tmp_path / "clip_policy_v2.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    editorial.clear_cache()


def test_v1_and_v2_load():
    editorial.clear_cache()
    assert editorial.load(1).version == 1
    assert editorial.load(2).version == 2
    assert editorial.policy_version(2) == "clip_policy_v2"


def test_active_version_comes_from_environment(monkeypatch):
    monkeypatch.delenv("CHOPSTR_POLICY_VERSION", raising=False)
    editorial.clear_cache()
    assert editorial.active_version() == 1
    assert editorial.load().version == 1 and editorial.policy_version() == "clip_policy_v1"
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
    assert editorial.active_version() == 2
    assert editorial.load().version == 2 and editorial.policy_version() == "clip_policy_v2"
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", " 1 ")
    assert editorial.load().version == 1
    editorial.clear_cache()


def test_typo_in_rollback_switch_fails_loudly(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "v2")
    with pytest.raises(editorial.PolicyError, match="keine Fassungsnummer"):
        editorial.active_version()


def test_unknown_version_fails_loudly(monkeypatch):
    monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "9")
    editorial.clear_cache()
    with pytest.raises(editorial.PolicyError, match="nicht gefunden"):
        editorial.load()
    editorial.clear_cache()


def test_v1_pins_are_the_versions_loaded_before_ap0b():
    assert editorial.load(1).prompt_pins == {
        "system_editor": 1, "propose_moments": 1, "score_clip": 2,
        "story_graph_confirm": 1, "hooks": 1, "post_caption": 1,
    }  # fmt: skip
    assert editorial.load(1).prompt_pins == editorial.V1_PROMPT_PINS


def test_v2_pins_match_v1_and_switches_match_implementation(v2_raw):
    """Pins wie v1 plus die Änderungen in V2_PIN_CHANGES; ein Schalter steht genau dann auf true,
    wenn sein Code gebaut ist und ihn liest (V2_IMPLEMENTED_SWITCHES)."""
    assert editorial.load(2).prompt_pins == {**editorial.V1_PROMPT_PINS, **editorial.V2_PIN_CHANGES}
    assert editorial.V2_IMPLEMENTED_SWITCHES.issubset(editorial.V2_SWITCHES)
    for path in editorial.V2_SWITCHES:
        value = v2_raw["implementation"]
        for part in path.split("."):
            value = value[part]
        assert value is (path in editorial.V2_IMPLEMENTED_SWITCHES), path


def test_trim_switch_is_registered_but_the_rule_stays_off(v2_raw):
    """AP7 verdrahtet: der Code liest den Schalter (registriert und true), die Regel trim.enabled bleibt bis
    zum Blindvergleich false; wirksam ist die Kürzung nur mit beiden (``trim_settings`` ``enabled``)."""
    assert "trim.enabled" in editorial.V2_IMPLEMENTED_SWITCHES
    assert v2_raw["implementation"]["trim"]["enabled"] is True and v2_raw["trim"]["enabled"] is False
    assert editorial.trim_settings(editorial.load(2))["enabled"] is False


def test_v2_rules_are_a_copy_of_v1(v2_raw):
    """Jede v1-Regel steht unverändert in v2 und der Prompt-Text ist gleich; v2 darf Abschnitte und
    Schlüssel ergänzen (Arbeitspakete). Anders sind nur Kopf, neue Abschnitte, neue Schlüssel und die
    Begründung bei offene_frage, die nicht mehr auf den widerlegten Zeigarnik-Effekt verweist."""
    import yaml

    v1_raw = yaml.safe_load((editorial.policy_dir() / "clip_policy_v1.yaml").read_text(encoding="utf-8"))

    def v1_rules_kept(old, new, path):
        if isinstance(old, dict):
            assert isinstance(new, dict), path
            for key, value in old.items():
                assert key in new, f"{path}.{key}"
                v1_rules_kept(value, new[key], f"{path}.{key}")
        else:
            assert new == old, path

    for section in editorial.RULE_SECTIONS:
        if section == "rubrik":
            continue
        v1_rules_kept(v1_raw[section], v2_raw[section], section)
    assert v2_raw["rubrik"]["skala_max"] == v1_raw["rubrik"]["skala_max"]
    for old, new in zip(v1_raw["rubrik"]["kriterien"], v2_raw["rubrik"]["kriterien"], strict=True):
        assert {k: v for k, v in old.items() if k != "herkunft"} == {k: v for k, v in new.items() if k != "herkunft"}
    open_question = next(k for k in editorial.load(2).kriterien if k.schluessel == "offene_frage")
    assert "Zeigarnik" not in open_question.herkunft and "Ovsiankina" in open_question.herkunft
    assert editorial.load(1).als_prompt_text() == editorial.load(2).als_prompt_text()


def test_every_v2_rule_has_an_origin(v2_raw):
    paths = editorial.rule_paths(v2_raw)
    assert set(paths) == set(v2_raw["origins"])
    for path in paths:
        entry = v2_raw["origins"][path]
        assert entry["origin"] in {"F", "H", "R", "G"}, path
        assert entry["source"].strip(), path
    # Recherche: das Längenfenster aus „105 Beispielclips“ ist nicht belastbar, G gibt es noch nicht.
    for path in ("laenge.ziel_s", "laenge.gut_von_s", "laenge.gut_bis_s", "rubrik.kriterien.offene_frage"):
        assert v2_raw["origins"][path]["origin"] == "H", path
    assert not any(e["origin"] == "G" for e in v2_raw["origins"].values())


def test_v2_text_has_no_dashes():
    import re

    text = (editorial.policy_dir() / "clip_policy_v2.yaml").read_text(encoding="utf-8")
    assert "–" not in text and "—" not in text
    assert not re.search(r"\S - ", text)  # Bindestrich als Gedankenstrich, YAML-Listenzeichen ausgenommen


@pytest.mark.parametrize("section", ["prompts", "implementation", "origins"])
def test_v2_without_required_section_fails_loudly(tmp_path, monkeypatch, v2_raw, section):
    del v2_raw[section]
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match=f"Pflichtabschnitte fehlen: {section}"):
        editorial.load(2)
    editorial.clear_cache()


def test_v2_rule_without_origin_fails_loudly(tmp_path, monkeypatch, v2_raw):
    del v2_raw["origins"]["laenge.ziel_s"]
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="Regeln ohne Herkunft in origins: laenge.ziel_s"):
        editorial.load(2)
    editorial.clear_cache()


def test_v2_orphaned_origin_and_bad_status_fail_loudly(tmp_path, monkeypatch, v2_raw):
    v2_raw["origins"]["laenge.gibt_es_nicht"] = {"origin": "H", "source": "x"}
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="origins nennt Regeln, die es nicht gibt: laenge.gibt_es_nicht"):
        editorial.load(2)
    del v2_raw["origins"]["laenge.gibt_es_nicht"]
    v2_raw["origins"]["laenge.ziel_s"] = {"origin": "X", "source": "x"}
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="muss F, H, R oder G sein"):
        editorial.load(2)
    editorial.clear_cache()


def test_v2_without_pin_or_switch_fails_loudly(tmp_path, monkeypatch, v2_raw):
    del v2_raw["prompts"]["hooks"]
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="prompts pinnt nicht: hooks"):
        editorial.load(2)
    v2_raw["prompts"]["hooks"] = 1
    del v2_raw["implementation"]["cut"]
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="implementation ohne Schalter: cut.padding"):
        editorial.load(2)
    editorial.clear_cache()


def test_file_name_and_version_must_match(tmp_path, monkeypatch, v2_raw):
    v2_raw["version"] = 3
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="nennt version 3, erwartet 2"):
        editorial.load(2)
    editorial.clear_cache()


def test_v2_origins_name_matching_sources_for_scale_and_standalone():
    """L9: Die Skala stammt aus der Masterclass (H) und weicht von den Ankern 0 bis 4 aus Master-Prompt
    Abschnitt 19 ab; Gegenposition 1 (Hook-Gleichung) ist dafür keine Quelle. Bei standalone sind Regel
    (R) und Gewicht (H) getrennt ausgewiesen."""
    origins = editorial.load(2).roh["origins"]
    scale = origins["rubrik.skala_max"]
    assert scale["origin"] == "H"
    assert "Masterclass Modul 10.2" in scale["source"] and "Master-Prompt Abschnitt 19" in scale["source"]
    assert "Gegenposition 1" not in scale["source"]
    standalone = origins["rubrik.kriterien.standalone"]
    assert standalone["origin"] == "R" and standalone["weight_origin"] == "H"
    assert "0,20" in standalone["weight_source"] and "Gewicht" not in standalone["source"]
    for path, entry in origins.items():
        if "weight_origin" in entry:
            assert entry["weight_origin"] in editorial.ORIGIN_VALUES, path
            assert str(entry.get("weight_source") or "").strip(), path


# -- AP9: Register der Schlüssel, Ausgabeumfang, Pin score_clip_v3 ----------------------------------------------
def _reader(ref: str):
    import importlib

    module, qualname = ref.split(":")
    obj = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def test_ap9_every_v2_rule_leaf_is_registered(v2_raw):
    """Jeder Blattschlüssel der Fassung 2 steht in implementation.keys mit Status; implemented und partial nennen
    eine lesende Funktion in IMPLEMENTED_KEYS, partial und not_implemented einen Grund."""
    register = editorial.key_register(editorial.load(2))
    paths = editorial.rule_paths(v2_raw)
    assert set(register) == set(paths)
    for path in paths:
        entry = register[path]
        assert entry["status"] in editorial.KEY_STATUSES, path
        if entry["status"] == "not_implemented":
            assert path not in editorial.IMPLEMENTED_KEYS, path
        else:
            assert path in editorial.IMPLEMENTED_KEYS, path
        if entry["status"] != "implemented":
            reason = str(entry.get("reason") or "")
            assert reason.strip(), path
            assert "–" not in reason and "—" not in reason and " - " not in reason, path
    assert set(editorial.IMPLEMENTED_KEYS) <= set(paths), "keine Funktion für einen Schlüssel, den es nicht gibt"


def test_ap9_every_registered_reader_exists_and_names_its_key():
    """Die Funktion existiert und nennt den Schlüssel (letzter oder vorletzter Pfadteil) im Quelltext."""
    import inspect

    for path, ref in {**editorial.IMPLEMENTED_KEYS, **editorial.IMPLEMENTED_BEHAVIOURS}.items():
        obj = _reader(ref)
        func = obj.fget if isinstance(obj, property) else obj
        assert callable(func), (path, ref)
        if path in editorial.IMPLEMENTED_KEYS:
            source = inspect.getsource(func)
            assert any(part in source for part in path.split(".")[-2:]), (path, ref)
    rescore = inspect.getsource(_reader(editorial.IMPLEMENTED_BEHAVIOURS["rescore_after_extension"]))
    assert "story_score.score(" in rescore and "heal_rounds" in rescore


def test_ap9_register_names_the_dead_keys_from_the_plan():
    register = editorial.key_register(editorial.load(2))
    for path in (
        "zusammenhang.max_gedanken", "ausschluss.insiderwitz_ohne_kontext", "audio.merkmale.lachen",
        "audio.merkmale.applaus", "audio.merkmale.pause_vor_aussage",
    ):  # fmt: skip
        assert register[path]["status"] == "not_implemented", path
    for path in ("einstieg.nie_mitten_im_satz", "ausstieg.verbklammer_nicht_trennen", "zusammenhang.mindest_dichte"):
        assert register[path]["status"] == "implemented", path
    assert editorial.key_register(editorial.load(1)) == {}


def test_ap9_output_settings_and_rollback(v2_raw, tmp_path, monkeypatch):
    assert editorial.output_settings(editorial.load(2)) == {"max_candidates": 10, "redundancy_jaccard": 0.6}
    assert editorial.output_settings(editorial.load(1)) is None
    assert "output.max_candidates" in editorial.V2_IMPLEMENTED_SWITCHES
    v2_raw["output"]["max_candidates"] = 20
    _write_v2(tmp_path, monkeypatch, v2_raw)
    assert editorial.output_settings(editorial.load(2))["max_candidates"] == 20
    v2_raw["implementation"]["output"]["max_candidates"] = False
    _write_v2(tmp_path, monkeypatch, v2_raw)
    assert editorial.output_settings(editorial.load(2)) is None
    v2_raw["implementation"]["output"]["max_candidates"] = True
    v2_raw["output"]["redundancy_jaccard"] = 0
    _write_v2(tmp_path, monkeypatch, v2_raw)
    with pytest.raises(editorial.PolicyError, match="redundancy_jaccard"):
        editorial.output_settings(editorial.load(2))
    editorial.clear_cache()


def test_ap9_v2_pins_score_clip_v3_and_v1_keeps_v2():
    from chopstr_worker import prompts

    assert editorial.V2_PIN_CHANGES["score_clip"] == 3
    assert prompts.load_pinned("score_clip", editorial.load(2)).prompt_version == "score_clip_v3"
    assert prompts.load_pinned("score_clip", editorial.load(1)).prompt_version == "score_clip_v2"
