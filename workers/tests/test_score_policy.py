"""Der Bewertungsweg über das Sprachmodell liest aus der redaktionellen Grundlage.

Geprüft wird nicht, ob eine Bewertung „gut" ist, sondern ob sie aus der richtigen Quelle stammt.
Eine Rubrik, die im Prompt und in der Grundlage getrennt gepflegt wird, läuft auseinander, ohne dass
es jemand merkt: Es kommen weiter Clips heraus, nur nach einem Massstab, den niemand beschlossen hat.

Ausserdem gesichert: die alten fünf Rubrik-Schlüssel bleiben im Ergebnis. Daran hängen Bestandszeilen
in ``candidates.rubric`` und die Web-App, und die lassen sich nicht nachbewerten.
"""

from __future__ import annotations

import logging

import pytest

from chopstr_worker import config, editorial, prompts
from chopstr_worker.pipeline import segment, story_score
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words

BRIEF = {"audience": "Gründer im DACH-Raum", "wanted": "Fehler, Zahlen", "exclude": "Werbung", "platform": "linkedin"}


@pytest.fixture
def policy():
    return editorial.load()


@pytest.fixture
def sents():
    return segment.sentences_from_words(demo_words())


def antwort_der_grundlage(policy, punkte: dict[str, float] | None = None, beleg: str = "", **extra) -> dict:
    """Antwort, wie sie ein Sprachmodell zu ``score_clip_v2`` liefert: nur die sieben Kriterien."""
    punkte = punkte or {k.schluessel: policy.skala_max for k in policy.kriterien}
    r: dict = {
        "unresolved_references": [],
        "needs_earlier_context": False,
        "ends_before_answer": False,
        "is_humor": False,
        "sensitive_topic": False,
        "suggested_title_card": "",
        "why": "Fake-Bewertung.",
    }
    for k in policy.kriterien:
        r[k.schluessel] = punkte[k.schluessel]
        r[f"{k.schluessel}_evidence"] = beleg
    return r | extra


def alte_antwort(beleg: str = "", **extra) -> dict:
    """Antwort in der Rubrik von ``score_clip_v1``: fünf Kriterien auf 0 bis 10."""
    r: dict = {
        "unresolved_references": [],
        "needs_earlier_context": False,
        "ends_before_answer": False,
        "hook": 8, "payoff": 7, "specificity": 9, "tension": 6, "audience_fit": 7,
        "is_humor": False,
        "sensitive_topic": False,
        "suggested_title_card": "",
        "why": "Fake-Bewertung.",
    }  # fmt: skip
    for k in story_score.LEGACY_KEYS:
        r[f"{k}_evidence"] = beleg
    return r | extra


def bewerte(monkeypatch, sents, antwort: dict) -> tuple[dict, dict]:
    """``story_score.score`` mit fester Antwort. Liefert Ergebnis und das, was ans Modell ging."""
    gesehen: dict = {}

    def fake_structured(self_llm, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        gesehen.update(system=system, user=user, schema=schema, tool=tool_name, prompt_version=prompt_version)
        return dict(antwort)

    monkeypatch.setattr(LLM, "structured", fake_structured)
    monkeypatch.setenv("LLM_PROVIDER", "selfhost-eu")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://llm.intern")
    monkeypatch.setenv("SELFHOST_LLM_MODEL", "test-model")
    config.reload()
    llm = LLM(Tenant(id="ws", tier="standard"), s=config.settings())
    return story_score.score(sents, BRIEF, llm), gesehen


# -- Der Prompt speist sich aus der Grundlage ------------------------------------------------------
def test_gerenderter_prompt_traegt_alle_sieben_kriterien(monkeypatch, policy, sents):
    _, gesehen = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    for k in policy.kriterien:
        assert k.schluessel in gesehen["user"], f"{k.schluessel} fehlt im Prompt"
        assert k.frage in gesehen["user"], f"Frage zu {k.schluessel} fehlt im Prompt"


def test_gerenderter_prompt_traegt_das_laengenfenster_der_grundlage(monkeypatch, policy, sents):
    _, gesehen = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    assert f"gut zwischen {policy.gut_von_s:.0f} und {policy.gut_bis_s:.0f} s" in gesehen["user"]
    assert f"Ziel {policy.ziel_s:.0f} s" in gesehen["user"]


def test_gerenderter_prompt_hat_keinen_offenen_platzhalter(monkeypatch, policy, sents):
    _, gesehen = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    assert "{policy}" not in gesehen["user"] and "{candidate_numbered}" not in gesehen["user"]
    assert gesehen["prompt_version"] == "score_clip_v2"


def test_prompt_verlangt_belegzitate_und_die_skala_der_grundlage(monkeypatch, policy, sents):
    _, gesehen = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    assert "_evidence" in gesehen["user"] and "wörtliches Zitat" in gesehen["user"]
    assert f"0 bis {policy.skala_max}" in gesehen["user"]
    # Die alte Fassung führte hier ihre eigene Rubrik auf einer Skala von 0 bis 10.
    alt = prompts.load("score_clip", 1)
    assert "SCORES 0 bis 10" in alt.body and "SCORES 0 bis 10" not in gesehen["user"]


def test_prompt_behaelt_die_pflichtkriterien_der_alten_fassung(monkeypatch, policy, sents):
    _, gesehen = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    for gate in ("unresolved_references", "needs_earlier_context", "ends_before_answer"):
        assert gate in gesehen["user"]


def test_antwortschema_kommt_aus_der_grundlage(monkeypatch, policy, sents):
    _, gesehen = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    props = gesehen["schema"]["properties"]
    for k in policy.kriterien:
        assert props[k.schluessel]["maximum"] == policy.skala_max
        assert f"{k.schluessel}_evidence" in props


# -- Gewichte --------------------------------------------------------------------------------------
def test_gewichte_stammen_aus_der_grundlage(policy):
    assert story_score.policy_weights() == policy.gewichte


def test_alte_fuenf_gewichte_sind_die_projektion_der_grundlage(policy):
    """``story_engine`` rechnet über die alten fünf Schlüssel und erwartet Summe 1.

    ``standalone`` und ``emotion`` haben dort keine Entsprechung; die übrigen fünf behalten ihr
    Verhältnis aus der Grundlage und werden normiert.
    """
    w = story_score.weights()
    assert set(w) == set(story_score.LEGACY_KEYS)
    assert sum(w.values()) == pytest.approx(1.0, abs=0.001)
    anteil = sum(policy.gewichte[pk] for pk in story_score.POLICY_TO_LEGACY)
    for pk, legacy in story_score.POLICY_TO_LEGACY.items():
        assert w[legacy] == pytest.approx(policy.gewichte[pk] / anteil, abs=0.0001)


def test_reihenfolge_der_gewichte_bleibt_die_der_grundlage(policy):
    w = story_score.weights()
    nach_grundlage = sorted(story_score.POLICY_TO_LEGACY, key=lambda pk: -policy.gewichte[pk])
    nach_projektion = sorted(story_score.POLICY_TO_LEGACY, key=lambda pk: -w[story_score.POLICY_TO_LEGACY[pk]])
    assert nach_grundlage == nach_projektion


def test_frontmatter_der_aktuellen_fassung_stimmt_mit_der_grundlage_ueberein():
    """Das Frontmatter darf die Gewichte mitführen, aber es muss dieselben sein."""
    assert story_score.weight_drift(prompts.load("score_clip", 2)) == {}


def test_abweichendes_frontmatter_wird_erkannt(policy):
    """Die Bestandsfassung v1 trägt die alten Gewichte. Genau das soll auffallen."""
    drift = story_score.weight_drift(prompts.load("score_clip", 1))
    assert "hook" in drift
    frontmatter, grundlage = drift["hook"]
    assert frontmatter == pytest.approx(0.30)
    assert grundlage == pytest.approx(story_score.weights()["hook"])


def test_abweichendes_frontmatter_wird_geloggt_und_die_grundlage_gewinnt(policy, caplog):
    p = prompts.parse(
        "---\nname: score_clip\nversion: 9\ntool: score_clip\n"
        "weights: {standalone: 0.90, hook: 0.10, offene_frage: 0.0, spezifitaet: 0.0, "
        "emotion: 0.0, aufloesung: 0.0, zielgruppe: 0.0}\n---\nEgal.\n"
    )
    drift = story_score.weight_drift(p)
    assert drift["standalone"] == (pytest.approx(0.90), pytest.approx(policy.gewichte["standalone"]))
    with caplog.at_level(logging.WARNING, logger="chopstr.story"):
        w = story_score.weights(p)
    assert "Grundlage gewinnt" in caplog.text
    assert w == story_score.legacy_weights()  # die Zahlen aus dem Prompt wirken nicht


# -- Bewertung -------------------------------------------------------------------------------------
def test_volle_punktzahl_ergibt_die_gesamtpunktzahl_der_grundlage(monkeypatch, policy, sents):
    span = sents[0:4]
    beleg = " ".join(span[0].text.split()[:5])
    r, _ = bewerte(monkeypatch, span, antwort_der_grundlage(policy, beleg=beleg))
    assert r["total"] == pytest.approx(policy.punkte_gesamt)
    assert r["rubric_points"] == {k.schluessel: policy.skala_max for k in policy.kriterien}
    assert r["rubric_guessed"] == []
    assert r["ungrounded_evidence"] == []
    assert r["policy_version"] == editorial.policy_version(policy.version)


def test_null_punkte_ergeben_null(monkeypatch, policy, sents):
    punkte = {k.schluessel: 0 for k in policy.kriterien}
    r, _ = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy, punkte))
    assert r["total"] == 0.0
    assert all(v == 0 for v in r["rubric_points"].values())


def test_alte_fuenf_schluessel_bleiben_im_ergebnis(monkeypatch, policy, sents):
    """Bestandsdaten und Web-App kennen nur diese fünf. Sie dürfen nie fehlen."""
    r, _ = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy))
    for k in story_score.RUBRIC_SCHEMA["required"]:
        assert k in r, f"{k} fehlt, Bestandsdaten brechen"
    for k in story_score.LEGACY_KEYS:
        assert isinstance(r[k], int) and 0 <= r[k] <= 10
        assert r[k] == 10  # volle Punktzahl der Grundlage, umgerechnet auf die alte Skala


def test_halbe_punktzahl_landet_in_der_mitte_der_alten_skala(monkeypatch, policy, sents):
    punkte = {k.schluessel: policy.skala_max / 2 for k in policy.kriterien}
    r, _ = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy, punkte))
    assert all(r[k] == 5 for k in story_score.LEGACY_KEYS)
    assert r["total"] == pytest.approx(policy.punkte_gesamt / 2)


def test_alte_antwort_wird_auf_die_grundlage_abgebildet(monkeypatch, policy, sents):
    """Eine Antwort in der alten Rubrik muss weiter durchlaufen, sonst bricht der Heuristik-Weg."""
    span = sents[0:4]
    beleg = " ".join(span[0].text.split()[:5])
    r, _ = bewerte(monkeypatch, span, alte_antwort(beleg))
    assert set(r["rubric_points"]) == {k.schluessel for k in policy.kriterien}
    assert all(0 <= v <= policy.skala_max for v in r["rubric_points"].values())
    # Die gelieferten alten Werte bleiben unangetastet, sonst würde aus einer 9 eine 10 oder eine 5.
    for k, v in (("hook", 8), ("payoff", 7), ("specificity", 9), ("tension", 6), ("audience_fit", 7)):
        assert r[k] == v
    # Was die alte Rubrik nicht kennt, wird geraten und steht auch so im Ergebnis.
    assert set(r["rubric_guessed"]) == {"standalone", "emotion"}
    assert r["ungrounded_evidence"] == []


def test_geratenes_standalone_folgt_den_gates(monkeypatch, policy, sents):
    r, _ = bewerte(monkeypatch, sents[0:4], alte_antwort(needs_earlier_context=True))
    assert r["rubric_points"]["standalone"] == 0
    assert r["gate_passed"] is False


def test_antwort_ohne_jede_punktzahl_scheitert_laut(monkeypatch, sents):
    kaputt = {
        "unresolved_references": [], "needs_earlier_context": False, "ends_before_answer": False,
        "is_humor": False, "suggested_title_card": "", "why": "leer",
    }  # fmt: skip
    with pytest.raises(ValueError, match="weder die Kriterien der Grundlage noch die alten fünf"):
        bewerte(monkeypatch, sents[0:4], kaputt)


def test_verschachtelte_rubrik_des_heuristik_providers_wird_bevorzugt(monkeypatch, policy, sents):
    """Der Heuristik-Provider liefert die sieben unter ``rubrik`` und die alten fünf daneben.

    Dann zählt die Grundlage, nicht die Rückrechnung aus den alten Werten. ``hook`` steht in beiden
    Rubriken und darf hier nicht als Wert der Grundlage missverstanden werden.
    """
    rubrik = {k.schluessel: policy.skala_max for k in policy.kriterien}
    r, _ = bewerte(monkeypatch, sents[0:4], alte_antwort(rubrik=rubrik))
    assert r["total"] == pytest.approx(policy.punkte_gesamt)
    assert r["rubric_guessed"] == []
    assert r["hook"] == 8  # alter Wert bleibt alter Wert
    assert r["rubric_points"]["hook"] == policy.skala_max


def test_erfundenes_belegzitat_wird_gemeldet(monkeypatch, policy, sents):
    r, _ = bewerte(monkeypatch, sents[0:4], antwort_der_grundlage(policy, beleg="Das steht nirgends im Clip."))
    assert "hook_evidence" in r["ungrounded_evidence"]
    assert "emotion_evidence" in r["ungrounded_evidence"]
