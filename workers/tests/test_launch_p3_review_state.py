"""Lane P3, Aufgaben 3 und 4: drei Ergebnisklassen (``rubric.review_state``, Regel 14), Auto-Annahme nur bei
``passed``, Titelkarte als Kontextreparatur mit Zitatprüfung und erneuter Prüfung (Regel 2).

Fassung 2 aus einer Kopie der Richtlinie, spaCy fest aus.
"""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest
import yaml

from chopstr_worker import editorial
from chopstr_worker.activities import analyze
from chopstr_worker.pipeline import dach_nlp, release_gate, segment, story_engine
from tests.test_critic import CONTRADICTION, GATES_OFF, SEARCH_OFF, finding
from tests.test_story_engine import BRIEF, brain, llm  # noqa: F401  (Fixtures)
from tests.transcript_fixtures import demo_words, make_words

PLAIN = "[1] (SPEAKER_00) Rabatte bringen sofort mehr Umsatz."


@pytest.fixture
def policy(monkeypatch, tmp_path):
    source = editorial.policy_dir()

    def make(**overrides):
        for path in source.glob("clip_policy_v*.yaml"):
            shutil.copy(path, tmp_path)
        target = tmp_path / "clip_policy_v2.yaml"
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
        for dotted, value in overrides.items():
            node = data
            *parents, leaf = dotted.split(".")
            for part in parents:
                node = node[part]
            node[leaf] = value
        target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path))
        monkeypatch.setenv("CHOPSTR_POLICY_VERSION", "2")
        monkeypatch.setattr(dach_nlp, "nlp", lambda: None)
        editorial.clear_cache()
        return editorial.load()

    yield make
    editorial.clear_cache()


def assert_contract(state: dict) -> None:
    assert set(state) == {"state", "reasons", "repair"}
    assert state["state"] in release_gate.REVIEW_STATES
    for r in state["reasons"]:
        assert set(r) == {"code", "text", "source_span", "origin"} and r["origin"] in release_gate.REVIEW_ORIGINS
        assert r["text"].endswith(".") and "—" not in r["text"] and " – " not in r["text"]
        assert r["source_span"] is None or set(r["source_span"]) == {"start_s", "end_s"}
    assert set(state["repair"]) == {"attempted", "kind", "result"}


# -- Ableitung der Klassen ---------------------------------------------------------------------------------


def test_review_state_passed_without_findings():
    state = release_gate.derive_review_state({"text": PLAIN})
    assert_contract(state)
    assert state == {"state": "passed", "reasons": [], "repair": {"attempted": False, "kind": None, "result": "not_attempted"}}


def test_review_state_uncertain_for_rule_hints_and_flags():
    words = make_words([("SPEAKER_00", "Er hat alles verändert.", 2.0)])
    rubric = {
        "text": PLAIN,
        "quality_gate_results": {"unresolved_pronoun": {"passed": False, "detail": "Pronomen „Er“ ohne Bezug im Clip", "evidence_word_ids": [0]}},
        "quality_gate_decision": {"decision": "reported", "reason": "gate:unresolved_pronoun nur berichtet"},
    }
    state = release_gate.derive_review_state(rubric, ["humor"], words=words)
    assert_contract(state)
    assert state["state"] == "uncertain"
    gate, humor = state["reasons"]
    assert gate == {"code": "gate:unresolved_pronoun", "text": "Regelhinweis unresolved_pronoun: Pronomen „Er“ ohne Bezug im Clip.",
                    "source_span": {"start_s": words[0]["start"], "end_s": words[0]["end"]}, "origin": "rule"}  # fmt: skip
    assert humor["code"] == "flag:humor" and humor["origin"] == "model"


def test_rule_hint_alone_is_never_blocked():
    """Regel 3: ein regelbasierter Hinweis bleibt origin rule und macht nie blocked."""
    rubric = {"text": PLAIN, "quality_gate_results": {k: {"passed": False, "detail": "Hinweis"} for k in ("back_reference", "unresolved_pronoun", "later_correction")}}
    state = release_gate.derive_review_state(rubric)
    assert state["state"] == "uncertain" and {r["origin"] for r in state["reasons"]} == {"rule"}


def test_claim_and_sensitive_topic_are_uncertain():
    state = release_gate.derive_review_state({"text": "[1] (A) Wir sparen damit 40.000 Euro im Jahr."}, ["sensitive_topic", "heuristic_only"])
    assert state["state"] == "uncertain"
    assert [r["code"] for r in state["reasons"]] == ["flag:sensitive_topic", "flag:claim"]
    assert state["reasons"][0]["origin"] == "rule", "Heuristik: Flag ist regelbasiert, nicht vom Modell"


def test_unconfirmed_model_findings_are_uncertain_confirmed_are_blocked():
    sents = segment.sentences_from_words(demo_words(), rule="v2")
    rubric = {"text": PLAIN, "critic": {"status": "checked", "confirmed": False, "heuristic": False},
              "critic_findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6])]}  # fmt: skip
    state = release_gate.derive_review_state(rubric, sents=sents)
    assert state["state"] == "uncertain" and state["reasons"][0]["origin"] == "model"
    assert state["reasons"][0]["source_span"] == {"start_s": round(sents[6].start, 3), "end_s": round(sents[6].end, 3)}
    rubric["critic"]["confirmed"] = True
    state = release_gate.derive_review_state(rubric, sents=sents)
    assert_contract(state)
    assert state["state"] == "blocked" and state["reasons"][0]["origin"] == "confirmed"
    assert state["repair"] == {"attempted": False, "kind": None, "result": "not_attempted"}


def test_heuristic_critic_never_blocks():
    rubric = {"text": PLAIN, "critic": {"status": "checked", "confirmed": True, "heuristic": True},
              "critic_findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6])]}  # fmt: skip
    state = release_gate.derive_review_state(rubric)
    assert state["state"] == "uncertain" and state["reasons"][0]["origin"] == "rule"


def test_gate_rejected_under_discard_hard_is_blocked_after_failed_heal():
    rubric = {
        "text": PLAIN,
        "quality_gate_results": {"later_correction": {"passed": False, "detail": "Spätere Korrektur", "evidence_word_ids": []}},
        "quality_gate_decision": {"decision": "rejected", "reason": "gate:later_correction"},
        "gate_heal": {"back": {"healed": False, "saetze": 1}},
    }
    state = release_gate.derive_review_state(rubric)
    assert state["state"] == "blocked" and state["reasons"][0]["code"] == "gate_rejected:later_correction"
    assert state["repair"] == {"attempted": True, "kind": "gate_heal", "result": "failed"}


def test_counter_reader_model_confirmed_blocks_second_only_is_uncertain():
    rubric = {"text": PLAIN, "counter_reader": {"confirmed": False, "model": {"findings": []},
              "additional_findings": [{"dimension": "time", "explanation": "Zeitraum fehlt."}]}}  # fmt: skip
    state = release_gate.derive_review_state(rubric)
    assert state["state"] == "uncertain" and state["reasons"][0]["code"] == "counter_reader_second:time"
    rubric["counter_reader"]["confirmed"] = True
    rubric["counter_reader"]["model"] = {"findings": [{"dimension": "attribution", "severity": "high", "explanation": "Andere Person."}]}
    assert release_gate.derive_review_state(rubric)["state"] == "blocked"


def test_review_settings_follow_switch_and_rule(policy):
    assert release_gate.review_settings(policy()) is True
    assert release_gate.review_settings(policy(**{"review.review_state": False})) is False
    assert release_gate.review_settings(policy(**{"implementation.review.review_state": False})) is False
    assert release_gate.review_settings(editorial.load(1)) is False


# -- Auto-Annahme --------------------------------------------------------------------------------------------


def test_auto_accept_only_for_passed():
    text = "[1] (A) Rabatte bringen Umsatz."
    assert analyze.auto_accept_blockers([], text, "", {"state": "passed", "reasons": []}) == []
    assert analyze.auto_accept_blockers([], text, "", {"state": "uncertain", "reasons": []}) == ["review_uncertain"]
    assert analyze.auto_accept_blockers(["humor"], text, "", {"state": "blocked"}) == ["review_blocked", "humor"]
    assert analyze.auto_accept_blockers([], text) == [], "ohne review_state (Fassung 1) wie vorher"
    reason = analyze.auto_hold_reason(["review_blocked"])
    assert reason.startswith(analyze.AUTO_HOLD_REASON_PREFIX), "verdict_reason bleibt kompatibel"


# -- Titelkarte ------------------------------------------------------------------------------------------------

CARD = [
    ("SPEAKER_00", "Ich erzähle euch heute etwas über Preise.", 3.0),
    ("SPEAKER_00", "Nur bei Stammkunden bringen Rabatte etwas.", 3.0),
    ("SPEAKER_00", "Rabatte bringen sofort mehr Umsatz.", 3.0),
    ("SPEAKER_00", "Wir haben das im Laden jeden Monat gesehen.", 3.0),
]


def candidate(first: int, last: int, sents) -> SimpleNamespace:
    text = segment.numbered(sents[first : last + 1])
    return SimpleNamespace(first_sent=first, last_sent=last, rubric={"text": text}, risk_flags=[], gates={}, story_graph_flags=[])


def test_title_card_from_literal_source_sentence_is_rechecked(policy):
    pol = policy()
    words = make_words(CARD)
    sents = segment.sentences_from_words(words, rule="v2")
    c = candidate(2, 3, sents)
    release_gate.annotate_review(c, words, sents, pol)
    card = c.rubric["repair_applied"]
    assert card["kind"] == "title_card" and card["text"] == CARD[1][1] and card["sentence_idx"] == 1
    assert card["source_span"] == {"start_s": round(sents[1].start, 3), "end_s": round(sents[1].end, 3)}
    assert card["recheck"]["passed"] is True and card["recheck"]["new_gate_failures"] == []
    assert "repair" not in c.rubric, "rubric.repair (Fassung 1) bleibt unberührt"
    state = c.rubric["review_state"]
    assert_contract(state)
    assert state["state"] == "uncertain" and "repair:title_card" in [r["code"] for r in state["reasons"]]
    assert state["repair"] == {"attempted": True, "kind": "title_card", "result": "passed"}
    det = c.rubric["counter_reader"]["deterministic"]
    assert "condition" in det["differs"]
    json.dumps(c.rubric, ensure_ascii=False)


def test_title_card_too_long_is_not_applied(policy):
    pol = policy(**{"context.title_card.max_words": 4})
    words = make_words(CARD)
    sents = segment.sentences_from_words(words, rule="v2")
    c = candidate(2, 3, sents)
    release_gate.annotate_review(c, words, sents, pol)
    assert "repair_applied" not in c.rubric
    assert c.rubric["title_card_attempt"]["recheck"]["passed"] is False
    assert c.rubric["review_state"]["repair"] == {"attempted": True, "kind": "title_card", "result": "failed"}


def test_no_title_card_without_condition_before(policy):
    pol = policy()
    words = make_words([CARD[0], CARD[2], CARD[3]])
    sents = segment.sentences_from_words(words, rule="v2")
    c = candidate(1, 2, sents)
    release_gate.annotate_review(c, words, sents, pol)
    assert "repair_applied" not in c.rubric and "title_card_attempt" not in c.rubric


def test_title_card_switch_off(policy):
    pol = policy(**{"context.title_card.enabled": False})
    words = make_words(CARD)
    sents = segment.sentences_from_words(words, rule="v2")
    c = candidate(2, 3, sents)
    release_gate.annotate_review(c, words, sents, pol)
    assert "repair_applied" not in c.rubric


def test_policy_v1_adds_nothing():
    words = make_words(CARD)
    sents = segment.sentences_from_words(words, rule="v2")
    c = candidate(2, 3, sents)
    release_gate.annotate_review(c, words, sents, editorial.load(1))
    assert c.rubric == {"text": segment.numbered(sents[2:4])}


# -- Im Lauf ------------------------------------------------------------------------------------------------


def test_run_marks_confirmed_critic_reject_as_blocked(brain, llm, policy):  # noqa: F811
    policy(**SEARCH_OFF, **GATES_OFF)
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    brain.critique = {"findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6], "Der Sprecher schränkt ein.")], "confirmed": True}
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    (c,) = report.verworfen
    state = c.rubric["review_state"]
    assert_contract(state)
    assert state["state"] == "blocked"
    assert any(r["origin"] == "confirmed" and r["code"] == "critic_confirmed:claim_contradicted" for r in state["reasons"])


def test_run_offered_candidates_carry_review_state(brain, llm, policy):  # noqa: F811
    policy(**SEARCH_OFF)
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert report.candidates
    for c in report.candidates:
        assert_contract(c.rubric["review_state"])
        assert c.rubric["review_state"]["state"] in ("passed", "uncertain")
        assert c.rubric["counter_reader"]["status"] == "checked"
    json.dumps(report.to_json(), ensure_ascii=False)
