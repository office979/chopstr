"""Kritiker (AP6b): Prüfung der Modellantwort, Heuristik-Handler, Verwerfen im Lauf, Budget.

Fassung 2 aus einer Kopie der Richtlinie, spaCy fest aus. Das Fake-Modell antwortet je Tool; der Kritiker
bekommt eine vorgegebene Antwort. Testsatz editorial_v1 Fall 3 (later_self_correction) und Fall 4
(reported_position) laufen über den Kritiker mit Fake-Antwort.
"""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest
import yaml

from chopstr_worker import config, editorial, heuristic_llm, prompts
from chopstr_worker.pipeline import critic, dach_nlp, segment, story_engine
from chopstr_worker.providers_llm import LLM, SchemaError
from chopstr_worker.residency import Tenant
from tests.editorial_v1 import harness
from tests.test_story_engine import BRIEF, FakeBrain
from tests.transcript_fixtures import demo_words

GATES_OFF = {"implementation.gates.discard_hard": False}
SEARCH_OFF = {"implementation.search.payoff_first": False}
CONTRADICTION = "Das heißt aber nicht, dass das für jede Branche gilt."


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Fassung 2 aus einer Kopie der Richtlinie mit geänderten Werten (Punktpfad zu Wert), spaCy fest aus."""
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


@pytest.fixture
def brain(monkeypatch) -> FakeBrain:
    b = FakeBrain()

    def fake_structured(self_llm, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        if tool_name == "critique_clip":
            b.calls.append((tool_name, prompt_version))
            b.critic_prompts.append(user)
            return json.loads(json.dumps(b.critique))
        return b.structured(system, user, schema, tool_name, prompt_version, job_type)

    b.critic_prompts = []
    monkeypatch.setattr(LLM, "structured", fake_structured)
    return b


@pytest.fixture
def llm(monkeypatch) -> LLM:
    monkeypatch.setenv("LLM_PROVIDER", "selfhost-eu")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://llm.intern")
    monkeypatch.setenv("SELFHOST_LLM_MODEL", "test-model")
    config.reload()
    return LLM(Tenant(id="ws", tier="standard"), s=config.settings())


class Answer:
    """Fake-Modell für ``critic.critique``: gibt eine feste Antwort und merkt sich den Prompt."""

    is_heuristic = False

    def __init__(self, answer: dict):
        self.answer = answer
        self.users: list[str] = []

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        assert tool_name == "critique_clip" and prompt_version == "critique_clip_v1"
        assert schema is critic.CRITIQUE_SCHEMA
        self.users.append(user)
        return json.loads(json.dumps(self.answer))


def finding(kind: str, severity: str, quote: str, refs: list[int], why: str = "Befund.") -> dict:
    return {"kind": kind, "severity": severity, "evidence_quote": quote, "sentence_refs": refs, "explanation": why}


def case_sents(cid: str) -> tuple[list[dict], list[segment.Sentence]]:
    words = harness.load_case(cid)["words"]
    return words, segment.sentences_from_words(words, rule="v2")


def span(first: int, last: int) -> SimpleNamespace:
    return SimpleNamespace(first_sent=first, last_sent=last)


# -- Prüfung der Antwort ------------------------------------------------------------------------------


def test_fake_finding_with_literal_quote_rejects(wired):
    pol = wired()
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    fake = Answer({"findings": [finding("claim_contradicted", "fidelity", "„das heißt aber nicht, dass das für jede Branche gilt“", [6])], "confirmed": True})
    res = critic.critique(span(1, 5), sents, words, fake, pol)
    assert res["confirmed"] is True and res["model_confirmed"] is True and res["heuristic"] is False
    assert res["reject"]["kind"] == "claim_contradicted" and res["reject"]["location"] == "context_after"
    assert res["reject"]["sentence_refs"] == [6] and res["dropped"] == []
    assert res["prompt_version"] == "critique_clip_v1"
    user = fake.users[0]
    assert "<clip>\n[1] (SPEAKER_00) Wir haben in unserer Branche" in user
    assert f"<context_after>\n[6] (SPEAKER_00) {CONTRADICTION}" in user
    assert "<context_before>\n[0] (SPEAKER_00) Ehrlich gesagt" in user


def test_ungrounded_finding_is_ignored(wired):
    pol = wired()
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    invented = finding("claim_contradicted", "fidelity", "Das gilt nur für Konzerne.", [6])
    fake = Answer({"findings": [invented], "confirmed": True})
    res = critic.critique(span(1, 5), sents, words, fake, pol)
    assert res["findings"] == [] and res["reject"] is None and res["confirmed"] is False
    assert [d["drop_reason"] for d in res["dropped"]] == ["ungrounded"]
    assert res["model_confirmed"] is True, "die Angabe des Modells bleibt sichtbar, verwirft aber nicht"


def test_quote_must_match_whole_words_and_refs_are_checked(wired):
    pol = wired()
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    fake = Answer({"findings": [
        finding("unclear_pronoun", "clarity", "Bran", [1]),  # Wortteil von „Branche“: nicht wörtlich
        finding("unclear_pronoun", "clarity", "Das hat alles verändert", [4, 99, True]),
        finding("other", "clarity", "Das hat alles verändert", [4]),
        finding("unclear_pronoun", "catastrophic", "Das hat alles verändert", [4]),
    ], "confirmed": False})  # fmt: skip
    res = critic.critique(span(1, 5), sents, words, fake, pol)
    assert [d["drop_reason"] for d in res["dropped"]] == ["ungrounded", "invalid", "invalid"]
    (kept,) = res["findings"]
    assert kept["sentence_refs"] == [4] and kept["location"] == "clip"


def test_clarity_finding_and_unconfirmed_fidelity_do_not_reject(wired):
    pol = wired()
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    fake = Answer({"findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6])], "confirmed": False})
    assert critic.critique(span(1, 5), sents, words, fake, pol)["reject"] is None
    fake = Answer({"findings": [finding("unclear_pronoun", "clarity", "Das hat alles verändert", [4])], "confirmed": True})
    res = critic.critique(span(1, 5), sents, words, fake, pol)
    assert res["reject"] is None and res["confirmed"] is False and len(res["findings"]) == 1


def test_answer_marked_heuristic_never_rejects(wired):
    pol = wired()
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    fake = Answer({"findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6])], "confirmed": True, "heuristic": True})
    res = critic.critique(span(1, 5), sents, words, fake, pol)
    assert res["heuristic"] is True and res["reject"] is None and res["confirmed"] is False
    assert res["findings"][0]["kind"] == "claim_contradicted"


def test_no_overlay_means_no_hook_check(wired):
    """Offener Punkt aus AP6a: erster Satz zu lang, kein Overlay (none_too_long). Der Kritiker prüft keinen
    Hook und schlägt keinen vor; ein Befund zum Hook wird verworfen (no_hook)."""
    pol = wired()
    words, sents = case_sents("reported_position")
    fake = Answer({"findings": [finding("hook_contradicted", "fidelity", "Ich sehe das anders.", [3])], "confirmed": True})
    res = critic.critique(span(1, 2), sents, words, fake, pol)
    assert res["hook_source"] == "none_too_long"
    assert "Text-Hook (Overlay): -" in fake.users[0]
    assert res["findings"] == [] and res["reject"] is None
    assert [d["drop_reason"] for d in res["dropped"]] == ["no_hook"]
    # Der Kritiker liefert keinen Hook-Text, also auch kein Overlay.
    assert set(res) == {"findings", "dropped", "confirmed", "model_confirmed", "reject", "heuristic", "hook_source", "prompt_version"}


# -- editorial_v1 Fall 3 und Fall 4 über den Kritiker -----------------------------------------------


def test_case_later_self_correction_rejects_the_isolated_claim(wired):
    """Fall 3: Der Clip endet auf „Werbung braucht man also eigentlich gar nicht.“; die Korrektur steht im Kontext."""
    pol = wired()
    words, sents = case_sents("later_self_correction")
    qual = harness.load_case("later_self_correction")["expected"]["later_qualification"]
    a, b = qual["qualification_word_range"]
    quote = " ".join(w["text"] for w in words[a : b + 1])
    fake = Answer({"findings": [finding("claim_contradicted", "fidelity", quote, [4], "Der Sprecher korrigiert die Aussage zwei Sätze später.")], "confirmed": True})
    res = critic.critique(span(0, 1), sents, words, fake, pol)
    assert res["reject"]["kind"] == "claim_contradicted" and res["reject"]["location"] == "context_after"
    # Mit Behauptung und Korrektur im Clip ist dasselbe Zitat Teil des Clips und kein Grund mehr, wenn das
    # Modell (richtig) nichts bestätigt.
    fake = Answer({"findings": [], "confirmed": False})
    assert critic.critique(span(0, 4), sents, words, fake, pol)["reject"] is None


def test_case_reported_position_rejects_the_quote_as_own_position(wired):
    """Fall 4: Der Clip gibt die These des Vertriebschefs wieder und endet vor „Ich sehe das anders.“"""
    pol = wired()
    words, sents = case_sents("reported_position")
    fake = Answer({"findings": [finding("reported_position", "fidelity", "Ich sehe das anders.", [3], "Die eigene Gegenposition fehlt im Clip.")], "confirmed": True})
    res = critic.critique(span(1, 2), sents, words, fake, pol)
    assert res["reject"]["kind"] == "reported_position" and res["reject"]["sentence_refs"] == [3]
    # Ein erfundenes Zitat („Kaltakquise ist die Zukunft“) steht nicht im Material und wird verworfen.
    fake = Answer({"findings": [finding("reported_position", "fidelity", "Kaltakquise ist die Zukunft.", [3])], "confirmed": True})
    res = critic.critique(span(1, 2), sents, words, fake, pol)
    assert res["reject"] is None and res["dropped"][0]["drop_reason"] == "ungrounded"


# -- Heuristik-Handler --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cid", "first", "last", "kind", "ref"),
    [("reported_position", 1, 2, "reported_position", 3), ("later_self_correction", 0, 1, "claim_contradicted", 3)],
)
def test_heuristic_handler_reports_gate_findings_without_rejecting(wired, cid, first, last, kind, ref):
    pol = wired()
    words, sents = case_sents(cid)
    user, _p, _meta = critic.build_prompt(sents, first, last, words, pol)
    out = heuristic_llm.answer("critique_clip", user, critic.CRITIQUE_SCHEMA)
    assert out["heuristic"] is True and out["confirmed"] is False
    hit = next(f for f in out["findings"] if f["kind"] == kind)
    assert hit["severity"] == "fidelity" and hit["sentence_refs"] == [ref]
    assert hit["evidence_quote"] == sents[ref].text, "ganzer Satz aus dem Material, nichts erfunden"
    assert hit["explanation"].startswith("Heuristik")

    heuristic = SimpleNamespace(is_heuristic=True, structured=lambda *a, **k: heuristic_llm.answer(a[3], a[1], a[2]))
    res = critic.critique(span(first, last), sents, words, heuristic, pol)
    assert res["heuristic"] is True and res["reject"] is None and res["confirmed"] is False
    assert res["dropped"] == [], "jedes Zitat der Heuristik ist wörtlich"
    assert any(f["kind"] == kind for f in res["findings"])


def test_heuristic_handler_without_problem_has_no_findings(wired):
    pol = wired()
    words, sents = case_sents("later_self_correction")
    user, _p, _meta = critic.build_prompt(sents, 0, 6, words, pol)
    assert heuristic_llm.answer("critique_clip", user) == {"findings": [], "confirmed": False, "heuristic": True}


def test_heuristic_run_never_discards_through_the_critic(wired, monkeypatch):
    wired()
    monkeypatch.setenv("LLM_PROVIDER", "local-heuristic")
    config.reload()
    llm = LLM(Tenant(id="ws", tier="sovereign"), s=config.settings(), provider="local-heuristic")
    words = harness.load_case("reported_position")["words"]
    report = story_engine.run(words, BRIEF, {}, None, llm)
    assert not [d for d in report.discarded if str(d.get("reason")).startswith("critic:")]
    for c in report.candidates:
        assert c.rubric["critic"]["status"] == "checked" and c.rubric["critic"]["heuristic"] is True
        assert isinstance(c.rubric["critic_findings"], list)


# -- Im Lauf ------------------------------------------------------------------------------------------


def test_run_discards_confirmed_fidelity_finding(brain, llm, wired):
    # Ohne harte Gates: deren Heilung nach hinten nähme den widersprechenden Satz in den Clip.
    wired(**SEARCH_OFF, **GATES_OFF)
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "Fehler mit Zahl."}]
    brain.critique = {"findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6], "Der Sprecher schränkt die Aussage ein.")], "confirmed": True}
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert report.candidates == []
    (d,) = [d for d in report.discarded if str(d["reason"]).startswith("critic:")]
    assert d["reason"] == "critic:claim_contradicted" and d["stage"] == "critic"
    assert CONTRADICTION in d["detail"] and "context_after" in d["detail"]
    (c,) = report.verworfen
    assert c.rubric["critic"]["confirmed"] is True and c.rubric["critic_findings"][0]["kind"] == "claim_contradicted"
    assert report.gate_rejections["by_gate"]["critic:claim_contradicted"] == {"failed": 1, "rejected": 1, "quote": 1.0}
    (cc,) = report.clip_candidates
    assert cc["decision"] == "reject" and "Kritiker" in cc["decision_reason"]
    assert "critique_clip_v1" in report.prompt_versions


def test_run_keeps_other_findings_in_the_rubric(brain, llm, wired):
    # Ohne harte Gates: deren Heilung nach hinten nähme den widersprechenden Satz in den Clip.
    wired(**SEARCH_OFF, **GATES_OFF)
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    brain.critique = {"findings": [finding("unclear_pronoun", "clarity", "Das hat alles verändert", [4])], "confirmed": False}
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    (c,) = report.candidates
    assert [f["kind"] for f in c.rubric["critic_findings"]] == ["unclear_pronoun"]
    assert c.rubric["critic"]["status"] == "checked" and c.rubric["critic"]["confirmed"] is False
    assert not report.gate_rejections
    json.dumps(report.to_json(), ensure_ascii=False)


def test_invalid_answer_leaves_the_candidate_unchecked(brain, llm, wired, monkeypatch):
    wired(**SEARCH_OFF)
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]

    def broken(*_a, **_k):
        raise SchemaError("Pflichtfelder fehlen: ['confirmed']")

    monkeypatch.setattr(critic, "critique", broken)
    (c,) = story_engine.run(demo_words(), BRIEF, {}, None, llm).candidates
    assert c.rubric["critic"]["status"] == "invalid_answer" and "confirmed" in c.rubric["critic"]["detail"]


def test_critic_respects_the_model_budget(brain, llm, wired, monkeypatch):
    """Mit verdrahteter Suche zählt BudgetLLM auch den Kritiker; ist das Budget erschöpft, bleibt der Kandidat
    ungeprüft und der Bericht nennt den Grund."""
    wired()
    monkeypatch.setattr(story_engine, "llm_budget_for", lambda sents, cfg, pol=None: 4)
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert report.llm_budget["used"] <= 4
    assert len(brain.calls) == report.llm_budget["used"], "jeder Modellaufruf zählt, auch der Kritiker"
    unchecked = [c for c in report.candidates if c.rubric["critic"]["status"] == "llm_budget"]
    assert unchecked, "das Budget reichte nicht für den Kritiker"
    assert any(d.get("stage") == "critic" and d["reason"] == "llm_budget" for d in report.discarded)

    monkeypatch.setattr(story_engine, "llm_budget_for", lambda sents, cfg, pol=None: 400)
    brain.calls.clear()
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    checked = [c for c in report.candidates if c.rubric["critic"]["status"] == "checked"]
    assert len(checked) == len(report.candidates) == sum(1 for t, _v in brain.calls if t == "critique_clip")
    assert report.llm_budget["used"] == len(brain.calls)


def test_critic_switch_off_is_the_rollback(brain, llm, wired):
    wired(**{**SEARCH_OFF, "implementation.roles.critic": False})
    brain.moments = lambda sents: [{"first_sent": 0, "last_sent": 5, "structure": "hook_build_payoff", "why": "x"}]
    brain.critique = {"findings": [finding("claim_contradicted", "fidelity", CONTRADICTION, [6])], "confirmed": True}
    report = story_engine.run(demo_words(), BRIEF, {}, None, llm)
    assert len(report.candidates) == 1 and "critic" not in report.candidates[0].rubric
    assert not [t for t, _v in brain.calls if t == "critique_clip"]
    assert "critique_clip_v1" not in report.prompt_versions


def test_critic_rule_and_switch_both_needed(wired):
    assert editorial.critic_enabled(wired()) is True
    assert editorial.critic_enabled(wired(**{"roles.critic": False})) is False
    assert editorial.critic_enabled(wired(**{"implementation.roles.critic": False})) is False
    assert editorial.critic_enabled(editorial.load(1)) is False
    with pytest.raises(editorial.PolicyError, match="roles.critic"):
        editorial.critic_enabled(wired(**{"roles.critic": "ja"}))


def test_v2_policy_declares_critic_rule_switch_and_pin():
    pol = editorial.load(2)
    assert pol.roh["roles"]["critic"] is True and pol.roh["implementation"]["roles"]["critic"] is True
    assert "roles.critic" in editorial.V2_SWITCHES and "roles.critic" in editorial.V2_IMPLEMENTED_SWITCHES
    assert pol.roh["origins"]["roles.critic"]["origin"] == "R" and "Abschnitt 22" in pol.roh["origins"]["roles.critic"]["source"]
    assert prompts.load_pinned("critique_clip", pol).prompt_version == "critique_clip_v1"
