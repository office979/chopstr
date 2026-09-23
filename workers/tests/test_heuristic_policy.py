"""Die Heuristik bezieht ihre Regeln aus der redaktionellen Grundlage, nicht aus dem Code.

Die Tests hier prüfen genau das: dass ``heuristic_llm`` die Zahlen und Listen aus
``packages/editorial/clip_policy_v1.yaml`` benutzt und nicht eigene. Ein fest verdrahteter Wert
fällt sonst nicht auf, weil das Ergebnis trotzdem plausibel aussieht.

Die Beispielsätze stammen, wo möglich, aus dem echten Material der Redaktion (in der YAML unter
``[E]`` dokumentiert): „Er ist ja offensichtlich kein unintelligenter Mann.“,
„Krankschreibungen werden in Deutschland massiv missbraucht.“ und
„Wo liegt das ungefähr? Eine Stunde von Göteborg entfernt.“
"""

from __future__ import annotations

import textwrap

import pytest

from chopstr_worker import editorial, heuristic_llm

# Aus dem Material
PRONOMEN_START = "Er ist ja offensichtlich kein unintelligenter Mann."
AUFSCHLAG = "Krankschreibungen werden in Deutschland massiv missbraucht."
ORGANISATORISCH = "Wo liegt das ungefähr? Eine Stunde von Göteborg entfernt."
NEUTRAL_SATZ = "Wir sprechen heute über das Wetter in dieser Stadt."
WIDERSPRUCH = "Alle sagen, man müsse dafür sehr viel Geld ausgeben. Das ist falsch."

HEUTIGER_MEDIAN_S = 19.0  # gemessener Median unserer Pipeline, siehe YAML-Kommentar zu ``laenge``
REFERENZ_MEDIAN_S = 41.0  # Median der 105 guten Beispielclips


@pytest.fixture
def policy():
    editorial.load.cache_clear()
    return editorial.load()


def _fuellsatz(worte: int) -> str:
    """Ein inhaltsleerer Satz mit genau ``worte`` Wörtern, damit die Längenschätzung exakt trifft."""
    assert worte >= 3
    return "Das " + " ".join(["eben"] * (worte - 3)) + " war so."


def _clip(sekunden: float, *saetze: str, sprecher: str = "SPEAKER_00") -> str:
    """Gerenderter Prompt (``[idx] (Sprecher) Text``), auf ``sekunden`` aufgefüllt.

    Aufgefüllt wird mit einem neutralen Satz, damit zwei Clips sich nur in der Länge unterscheiden
    und sonst denselben Inhalt haben.
    """
    zeilen: list[str] = []
    for satz in saetze:
        zeilen.extend(x.strip() for x in satz.split(" | "))
    ziel = round(sekunden * heuristic_llm.WORDS_PER_SECOND)
    rest = ziel - sum(len(z.split()) for z in zeilen)
    if rest >= 3:
        zeilen.append(_fuellsatz(rest))
    return "\n".join(f"[{i}] ({sprecher}) {t}" for i, t in enumerate(zeilen))


# -- Länge kommt aus der Grundlage -----------------------------------------------------------------
def test_die_laenge_kommt_aus_der_grundlage_und_nicht_aus_dem_code(policy, tmp_path, monkeypatch):
    """Mit einem anderen Fenster in der YAML muss sich das Urteil der Heuristik mitdrehen.

    Der Test ist der eigentliche Beweis, dass 20,0 und 60,0 aus dem Code verschwunden sind: Bei
    einem Fenster von 5 bis 12 Sekunden gilt ein Zehn-Sekunden-Clip als gut, bei der echten
    Grundlage nicht.
    """
    zehn_sekunden = _clip(10.0, AUFSCHLAG)
    assert heuristic_llm.score_clip(zehn_sekunden)["laenge_ok"] is False

    (tmp_path / "clip_policy_v1.yaml").write_text(
        textwrap.dedent(f"""
            version: 1
            laenge: {{ziel_s: 8, gut_von_s: 5, gut_bis_s: 12, hart_min_s: 3, hart_max_s: 20}}
            rubrik:
              skala_max: 2
              kriterien:
{textwrap.indent(_kriterien_yaml(), " " * 16)}
            bewertung: {{modus: sortieren, schwelle_schneiden: 10, schwelle_verwerfen: 7, punkte_gesamt: 14}}
            moment_typen: []
            einstieg: {{}}
            ausstieg: {{}}
            zusammenhang: {{}}
            audio: {{}}
            hook_vorziehen: {{}}
            ausschluss: {{}}
        """),
        encoding="utf-8",
    )
    editorial.load.cache_clear()
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
    try:
        assert heuristic_llm.score_clip(zehn_sekunden)["laenge_ok"] is True
    finally:
        editorial.load.cache_clear()


def _kriterien_yaml() -> str:
    schluessel = ("standalone", "hook", "offene_frage", "spezifitaet", "emotion", "aufloesung", "zielgruppe")
    gewicht = 1.0 / len(schluessel)
    return "\n".join(f"- {{schluessel: {s}, frage: x, gewicht: {gewicht:.6f}}}" for s in schluessel)


def test_unser_heutiger_median_bekommt_abzug_der_referenzmedian_nicht(policy):
    """19 s ist der Median unserer Pipeline, 41 s der der guten Beispielclips."""
    kurz = heuristic_llm.score_clip(_clip(HEUTIGER_MEDIAN_S, AUFSCHLAG))
    gut = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG))

    assert kurz["laenge_ok"] is False
    assert kurz["laenge_abzug"] > 0.8
    assert gut["laenge_ok"] is True
    assert gut["laenge_abzug"] == 0.0
    assert gut["punkte"] > kurz["punkte"]


def test_moment_im_guten_fenster_schlaegt_den_gleichen_moment_ausserhalb(policy):
    """Gleicher Inhalt, nur die Länge unterscheidet sich, nach unten wie nach oben."""
    im_fenster = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG))
    zu_kurz = heuristic_llm.score_clip(_clip(20.0, AUFSCHLAG))
    zu_lang = heuristic_llm.score_clip(_clip(68.0, AUFSCHLAG))

    assert im_fenster["punkte"] > zu_kurz["punkte"]
    assert im_fenster["punkte"] > zu_lang["punkte"]


# -- Rubrik auf sieben Kriterien -------------------------------------------------------------------
def test_alle_sieben_kriterien_stehen_im_ergebnis(policy):
    r = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG))
    assert set(r["rubrik"]) == {k.schluessel for k in policy.kriterien}
    for schluessel, wert in r["rubrik"].items():
        assert 0.0 <= wert <= policy.skala_max, schluessel
    assert r["skala_max"] == policy.skala_max
    assert r["policy_version"] == editorial.policy_version()


def test_die_alten_fuenf_schluessel_bleiben_erhalten(policy):
    """Bestandsdaten und die Web-App lesen weiterhin hook, payoff, specificity, tension, audience_fit."""
    r = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG, WIDERSPRUCH))
    for alt in ("hook", "payoff", "specificity", "tension", "audience_fit"):
        assert alt in r, alt
        assert isinstance(r[alt], int) and 0 <= r[alt] <= 10, alt
        assert f"{alt}_evidence" in r


def test_die_alten_fuenf_sind_die_neuen_umgerechnet(policy):
    """payoff ist aufloesung, specificity ist spezifitaet, tension ist offene_frage, audience_fit ist zielgruppe."""
    r = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG, WIDERSPRUCH))
    for alt, neu in heuristic_llm.ALT_AUS_NEU.items():
        erwartet = round(r["rubrik"][neu] / policy.skala_max * heuristic_llm.ALT_SKALA_MAX)
        assert abs(r[alt] - erwartet) <= 1, f"{alt} passt nicht zu {neu}"


def test_pronomen_ohne_bezug_kostet_bei_standalone(policy):
    """Beide Sätze stammen aus dem Material, siehe einstieg-Kommentar in der YAML."""
    mit_pronomen = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, PRONOMEN_START))
    mit_aufschlag = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG))

    assert mit_pronomen["rubrik"]["standalone"] < mit_aufschlag["rubrik"]["standalone"]
    assert mit_aufschlag["rubrik"]["standalone"] == policy.skala_max


def test_gastgeberfrage_am_anfang_ist_kein_hook(policy):
    """[R] Die Frage des Gastgebers ist Anlauf. Die eigene Frage des Sprechers dagegen ist ein Hook."""
    fremd = "\n".join(
        [
            "[0] (SPEAKER_01) Was würdest du heute anders machen?",
            f"[1] (SPEAKER_00) {AUFSCHLAG}",
            f"[2] (SPEAKER_00) {_fuellsatz(80)}",
        ]
    )
    eigen = "\n".join(
        [
            "[0] (SPEAKER_00) Was würdest du heute anders machen?",
            f"[1] (SPEAKER_00) {AUFSCHLAG}",
            f"[2] (SPEAKER_00) {_fuellsatz(80)}",
        ]
    )
    r_fremd = heuristic_llm.score_clip(fremd)
    r_eigen = heuristic_llm.score_clip(eigen)

    assert r_fremd["gastgeberfrage"] is True
    assert r_eigen["gastgeberfrage"] is False
    assert r_fremd["rubrik"]["hook"] < r_eigen["rubrik"]["hook"]
    assert r_fremd["rubrik"]["standalone"] < r_eigen["rubrik"]["standalone"]


def test_zielgruppe_bleibt_ein_ehrlicher_mittelwert(policy):
    """Ohne Wissen über die Zielgruppe darf die Heuristik keine Genauigkeit vortäuschen."""
    mitte = policy.skala_max / 2
    for text in (AUFSCHLAG, WIDERSPRUCH, NEUTRAL_SATZ, PRONOMEN_START):
        wert = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, text))["rubrik"]["zielgruppe"]
        assert mitte <= wert <= mitte + 0.5, text


def test_emotion_erkennt_wertung_und_nachdruck_nicht_aber_den_tonfall(policy):
    """Was die Näherung sieht (Wertungswörter, Nachdruck) und was nicht (alles Hörbare)."""
    sachlich = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, "Der Umsatz lag im zweiten Quartal bei dem Wert."))
    wertend = heuristic_llm.score_clip(
        _clip(REFERENZ_MEDIAN_S, "Das war der schlimmste Fehler, absolut furchtbar. | Das mache ich nie wieder.")
    )
    assert wertend["rubrik"]["emotion"] > sachlich["rubrik"]["emotion"]

    # Dieselben Wörter, nur lauter gesprochen: Text sieht keinen Unterschied. Das steht so im
    # Docstring von ``_emotion`` und ist der Grund, warum die Grundlage ``audio`` vorsieht.
    assert heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, "Der Umsatz lag im zweiten Quartal bei dem Wert."))[
        "rubrik"
    ]["emotion"] == sachlich["rubrik"]["emotion"]


# -- Moment-Typen ----------------------------------------------------------------------------------
def test_widerspruch_wird_erkannt_und_hebt_die_bewertung(policy):
    """„Alle sagen X. Das ist falsch.“ gegen einen neutralen Satz derselben Länge."""
    widerspruch = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, WIDERSPRUCH))
    neutral = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, NEUTRAL_SATZ))

    assert "contrarian" in widerspruch["moment_typen"]
    assert neutral["moment_typen"] == []
    assert widerspruch["laenge_s"] == neutral["laenge_s"]
    assert widerspruch["punkte"] > neutral["punkte"]


def test_typen_die_audio_brauchen_werden_aus_text_nicht_behauptet(policy):
    """Der Typ Konflikt hängt an der lauter werdenden Stimme, die der Text nicht sieht."""
    r = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, "Nein, das sehe ich anders. | Quatsch."))
    assert "konflikt" not in r["moment_typen"]


def test_zahl_hebt_die_spezifitaet(policy):
    mit = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, "Wir haben damals 40.000 Euro in dem Jahr verloren."))
    ohne = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, "Wir haben damals sehr viel Geld in dem Jahr verloren."))
    assert "zahl" in mit["moment_typen"]
    assert mit["rubrik"]["spezifitaet"] > ohne["rubrik"]["spezifitaet"]


# -- Ausschluss ------------------------------------------------------------------------------------
def test_organisationsgespraech_wird_niedrig_bewertet_aber_nicht_unterdrueckt(policy):
    """Entscheidung vom 24.09.2026: modus ``sortieren``. Nichts wird gesperrt, nur sortiert."""
    r = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, ORGANISATORISCH))
    inhalt = heuristic_llm.score_clip(_clip(REFERENZ_MEDIAN_S, AUFSCHLAG))

    assert policy.modus == "sortieren" and policy.sperrt is False
    assert r["organisatorisch"] is True
    assert r["punkte"] < inhalt["punkte"] / 3

    # Nicht unterdrückt: vollständiges Ergebnis, und keines der Gate-Felder wird gesetzt.
    for schluessel in ("hook", "payoff", "specificity", "tension", "audience_fit", "rubrik", "why"):
        assert schluessel in r
    assert r["unresolved_references"] == []
    assert r["needs_earlier_context"] is False
    assert r["ends_before_answer"] is False
    assert "Organisationsgespräch" in r["why"]


# -- Auswahl der Momente ---------------------------------------------------------------------------
def _langer_prompt(saetze: int = 60) -> str:
    """Wechselnde Sätze mit Ankern, lang genug für mehrere Vorschläge."""
    muster = [
        "Alle sagen, man müsse dafür sehr viel Geld ausgeben.",
        "Das ist falsch, und zwar aus einem einfachen Grund.",
        "Wir haben damals 40 Prozent unserer Marge dabei verloren.",
        "Das Wetter war an diesem Tag ziemlich durchwachsen.",
        "Ich dachte, das läuft von allein, und dann kam die Rechnung.",
        "Die Regel ist einfach: erst rechnen, dann verkaufen.",
    ]
    return "\n".join(f"[{i}] (SPEAKER_00) {muster[i % len(muster)]}" for i in range(saetze))


def test_vorschlaege_halten_das_laengenfenster_der_grundlage_ein(policy):
    moments = heuristic_llm.propose_moments(_langer_prompt())["moments"]
    assert moments
    sents = heuristic_llm.parse_numbered(_langer_prompt())
    for m in moments:
        span = sents[m["first_sent"] : m["last_sent"] + 1]
        est = heuristic_llm.estimate_seconds(span)
        assert policy.hart_min_s <= est <= policy.gut_bis_s, est


def test_moment_typen_ziehen_die_ankerwahl(policy):
    """Ein Satz mit Moment-Typ muss als Anker schwerer wiegen als derselbe Satz ohne."""
    mit_typ = {"idx": 0, "speaker": "SPEAKER_00", "text": "Ich dachte, das läuft. Und dann kam die Rechnung."}
    ohne_typ = {"idx": 0, "speaker": "SPEAKER_00", "text": "Ich glaube, das läuft. Danach kam die Rechnung."}
    assert heuristic_llm._anchor_score(mit_typ, policy) > heuristic_llm._anchor_score(ohne_typ, policy)


def test_vorschlaege_nennen_den_moment_typ_in_der_begruendung(policy):
    moments = heuristic_llm.propose_moments(_langer_prompt())["moments"]
    assert any("Moment-Typ" in m["why"] for m in moments)
    for m in moments:
        assert m["why"].startswith("Heuristik ohne Sprachmodell")
        assert "Sekunden" in m["why"]
