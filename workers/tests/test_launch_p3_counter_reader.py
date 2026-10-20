"""Lane P3, Aufgaben 2 und 6 (Regel 6): Gegenleser nach sechs Dimensionen, regelbasiert und mit Modell
(``counter_reader_v1``), zweites Modell nur gemessen, Hook-Verdichtung nach Regel 6.

Fassung 2 aus einer Kopie der Richtlinie, spaCy fest aus.
"""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest
import yaml

from chopstr_worker import config, editorial, providers_llm
from chopstr_worker.pipeline import critic, dach_nlp, fidelity, segment
from chopstr_worker.providers_llm import HEURISTIC_PROVIDER, LLM, SchemaError
from chopstr_worker.residency import Tenant
from tests.transcript_fixtures import demo_words

SPOKEN = "Ich habe in einer Woche rund 40.000 Euro verloren."
GOOD_HOOK = "Rund 40.000 Euro Verlust in einer Woche."
BAD_HOOK = "Diese Methode kostet dich 40.000 Euro."
MODEL_ON = {"context.counter_reader.model": True}


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


class Model:
    """Fake-Modell: antwortet je Tool mit einer festen Antwort und zählt die Aufrufe."""

    def __init__(self, counter: dict | None = None, provider: str = "selfhost-eu", heuristic: bool = False):
        self.counter = counter or {"findings": [], "confirmed": False}
        self.critique = {"findings": [], "confirmed": False}
        self.provider = provider
        self.is_heuristic = heuristic
        self.calls: list[str] = []

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        self.calls.append(tool_name)
        if tool_name == "counter_reader":
            assert prompt_version == "counter_reader_v1" and schema is critic.COUNTER_SCHEMA
            assert "<clip>" in user and "Text-Hook (Overlay):" in user
            return json.loads(json.dumps(self.counter))
        if tool_name == "critique_clip":
            return json.loads(json.dumps(self.critique))
        raise AssertionError(tool_name)


def differs(dim: str, clip_quote: str, hook_quote: str, severity: str = "high") -> dict:
    return {"dimension": dim, "verdict": "differs", "clip_quote": clip_quote, "hook_quote": hook_quote, "severity": severity, "explanation": "Der Hook ändert die Aussage."}


# -- Regel 6: Hook-Verdichtung ----------------------------------------------------------------------------


def test_rule6_example_condensed_hook_is_permissible():
    assert fidelity.hook_meaning_issues(GOOD_HOOK, SPOKEN) == []
    assert fidelity.hook_claim_check_v2(GOOD_HOOK, SPOKEN, meaning=True) == []


def test_rule6_example_method_hook_violates_attribution_and_causality():
    dims = {i["dimension"] for i in fidelity.hook_meaning_issues(BAD_HOOK, SPOKEN)}
    assert {"attribution", "causality"} <= dims
    issues = fidelity.hook_claim_check_v2(BAD_HOOK, SPOKEN, meaning=True)
    assert any(i.startswith("Zuschreibung") for i in issues) and any(i.startswith("Kausalität") for i in issues)


def test_rule6_certainty_time_and_magnitude():
    clip = "Ich glaube, wir haben 2019 etwa 30 Prozent verloren."
    assert {i["dimension"] for i in fidelity.hook_meaning_issues("Garantiert 30 Prozent Verlust.", clip)} >= {"certainty", "time", "magnitude"}
    assert fidelity.hook_meaning_issues("Ich glaube: 2019 etwa 30 Prozent verloren.", clip) == []


def test_rule6_check_follows_the_switch(policy):
    policy()
    assert fidelity.hook_claim_check_v2(BAD_HOOK, SPOKEN), "Gegenleser an: Regel 6 gilt im Claim-Check"
    policy(**{"context.counter_reader.enabled": False})
    assert fidelity.hook_claim_check_v2(BAD_HOOK, SPOKEN) == [], "Regel aus: Claim-Check wie vor Lane P3"


# -- Regelbasierter Gegenleser ----------------------------------------------------------------------------


def clip(*texts: str) -> list[dict]:
    return [{"text": t, "start_s": float(n), "end_s": float(n) + 0.9} for n, t in enumerate(texts)]


def test_counter_reader_has_one_finding_per_dimension_and_quotes():
    res = fidelity.counter_read(clip(SPOKEN), None, None, BAD_HOOK)
    assert [f["dimension"] for f in res["findings"]] == list(fidelity.COUNTER_DIMENSIONS)
    att = res["findings"][0]
    assert att["verdict"] == "differs" and att["source"] == "hook" and att["clip_quote"] and att["source_quote"] == "dich"
    assert "attribution" in res["differs"] and any(i["dimension"] == "causality" for i in res["hook_meaning"])


def test_counter_reader_finds_condition_in_context_before():
    before = {"text": "Nur bei Stammkunden bringen Rabatte etwas.", "start_s": 0.0, "end_s": 2.0}
    res = fidelity.counter_read(clip("Rabatte bringen sofort mehr Umsatz."), before, None)
    cond = next(f for f in res["findings"] if f["dimension"] == "condition")
    assert cond["verdict"] == "differs" and cond["source"] == "context_before"
    assert cond["source_quote"] == before["text"] and cond["source_span"] == {"start_s": 0.0, "end_s": 2.0}


def test_counter_reader_unrelated_neighbour_is_same():
    before = {"text": "Gestern hat es in Wien nicht geregnet, das Wetter war schön.", "start_s": 0.0, "end_s": 2.0}
    res = fidelity.counter_read(clip("Rabatte bringen sofort mehr Umsatz."), before, None, "Rabatte bringen sofort mehr Umsatz.")
    assert res["differs"] == []


def test_counter_reader_number_in_context_after():
    after = {"text": "Also eigentlich waren es 30 Prozent.", "start_s": 3.0, "end_s": 4.0}
    res = fidelity.counter_read(clip("Wir haben 40 Prozent Marge verloren."), None, after)
    assert next(f for f in res["findings"] if f["dimension"] == "number")["verdict"] == "differs"


# -- Gegenleser mit Modell und zweites Modell -------------------------------------------------------------


def test_model_quotes_are_checked_deterministically():
    kept, dropped = critic.check_counter_findings(
        [differs("attribution", "Ich habe", "dich"), differs("time", "im Jahr 2020", "dich"), {"dimension": "mood", "verdict": "differs"},
         {"dimension": "number", "verdict": "same"}],
        SPOKEN, BAD_HOOK,
    )  # fmt: skip
    assert [f["dimension"] for f in kept] == ["attribution"]
    assert [d["drop_reason"] for d in dropped] == ["ungrounded", "invalid"]


def test_confirmed_high_finding_rejects_and_second_model_is_only_measured(policy):
    pol = policy(**MODEL_ON)
    first = Model({"findings": [differs("attribution", "Ich habe", "dich")], "confirmed": True})
    second = Model({"findings": [differs("attribution", "Ich habe", "dich"), differs("time", "in einer Woche", "Diese Methode kostet dich 40.000 Euro.")], "confirmed": True}, provider="mistral-eu")
    res = critic.counter_read_model(SPOKEN, BAD_HOOK, first, pol, second)
    assert res["confirmed"] is True and res["reject"]["dimension"] == "attribution"
    assert res["model"]["status"] == "checked" and res["model"]["prompt_version"] == "counter_reader_v1"
    assert [f["dimension"] for f in res["additional_findings"]] == ["time"]
    assert res["rejected_by_second_only"] is False and res["second"]["provider"] == "mistral-eu"


def test_second_model_alone_never_rejects(policy):
    pol = policy(**MODEL_ON)
    first = Model({"findings": [], "confirmed": False})
    second = Model({"findings": [differs("attribution", "Ich habe", "dich")], "confirmed": True}, provider="mistral-eu")
    res = critic.counter_read_model(SPOKEN, BAD_HOOK, first, pol, second)
    assert res["confirmed"] is False and res["reject"] is None
    assert res["rejected_by_second_only"] is True and len(res["additional_findings"]) == 1


def test_low_or_unconfirmed_findings_do_not_reject(policy):
    pol = policy(**MODEL_ON)
    low = Model({"findings": [differs("attribution", "Ich habe", "dich", "low")], "confirmed": True})
    assert critic.counter_read_model(SPOKEN, BAD_HOOK, low, pol)["reject"] is None
    unconfirmed = Model({"findings": [differs("attribution", "Ich habe", "dich")], "confirmed": False})
    assert critic.counter_read_model(SPOKEN, BAD_HOOK, unconfirmed, pol)["reject"] is None


def test_heuristic_is_not_a_model_and_not_a_second_model(policy):
    pol = policy(**MODEL_ON)
    heur = Model(heuristic=True, provider=HEURISTIC_PROVIDER)
    res = critic.counter_read_model(SPOKEN, BAD_HOOK, heur, pol)
    assert res["model"]["status"] == "heuristic" and heur.calls == []
    first = Model()
    res = critic.counter_read_model(SPOKEN, BAD_HOOK, first, pol, Model(provider=HEURISTIC_PROVIDER, heuristic=True))
    assert res["second"] == {"status": "not_a_second_model", "provider": HEURISTIC_PROVIDER, "heuristic": True}
    assert first.calls == ["counter_reader"]


def test_no_hook_means_no_model_call(policy):
    pol = policy(**MODEL_ON)
    m = Model()
    assert critic.counter_read_model(SPOKEN, "", m, pol)["model"] == {"status": "no_hook"} and m.calls == []


def test_invalid_answer_is_reported_not_raised(policy):
    pol = policy(**MODEL_ON)

    class Broken(Model):
        def structured(self, *a, **k):
            raise SchemaError("Pflichtfelder fehlen: ['confirmed']")

    assert critic.counter_read_model(SPOKEN, BAD_HOOK, Broken(), pol)["model"]["status"] == "invalid_answer"


def test_second_call_counts_in_the_budget(policy):
    from chopstr_worker.pipeline.story_engine import BudgetLLM

    pol = policy(**MODEL_ON)
    budget = BudgetLLM(Model(), limit=1)
    res = critic.counter_read_model(SPOKEN, BAD_HOOK, budget, pol, Model(provider="mistral-eu"))
    assert res["model"]["status"] == "checked" and res["second"]["status"] == "llm_budget" and budget.used == 1
    budget = BudgetLLM(Model(), limit=5)
    critic.counter_read_model(SPOKEN, BAD_HOOK, budget, pol, Model(provider="mistral-eu"))
    assert budget.used == 2


def test_critique_runs_the_counter_reader_and_rejects_on_confirmed_finding(policy, monkeypatch):
    pol = policy(**MODEL_ON)
    words = demo_words()
    sents = segment.sentences_from_words(words, rule="v2")
    hook = critic.text_hook(" ".join(s.text for s in sents[0:6]), words[: sents[5].word_range[1] + 1])[0]
    assert hook == "Ehrlich gesagt war das der teuerste Fehler meiner Karriere."
    m = Model({"findings": [differs("certainty", "Ehrlich gesagt", "Ehrlich gesagt")], "confirmed": True})
    monkeypatch.setattr(providers_llm, "second_llm", lambda primary: None)
    cand = SimpleNamespace(first_sent=0, last_sent=5, rubric={})
    res = critic.critique(cand, sents, words, m, pol)
    assert m.calls == ["critique_clip", "counter_reader"]
    assert res["reject"]["kind"] == "counter_reader_certainty" and res["reject"]["location"] == "clip"
    assert cand.rubric["counter_reader"]["confirmed"] is True and "reject" not in cand.rubric["counter_reader"]
    # Ohne Modellteil (Standard: context.counter_reader.model false) ruft der Kritiker den Gegenleser nicht.
    m2 = Model()
    critic.critique(SimpleNamespace(first_sent=0, last_sent=5, rubric={}), sents, words, m2, policy())
    assert m2.calls == ["critique_clip"]


def test_second_llm_only_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "selfhost-eu")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://llm.intern")
    monkeypatch.setenv("SELFHOST_LLM_MODEL", "test-model")
    config.reload()
    primary = LLM(Tenant(id="ws", tier="standard"), s=config.settings())
    monkeypatch.delenv(providers_llm.SECOND_PROVIDER_ENV, raising=False)
    assert providers_llm.second_llm(primary) is None
    monkeypatch.setenv(providers_llm.SECOND_PROVIDER_ENV, "mistral-eu")
    second = providers_llm.second_llm(primary)
    assert isinstance(second, LLM) and second.provider == "mistral-eu" and second.tenant is primary.tenant
    monkeypatch.setenv(providers_llm.SECOND_PROVIDER_ENV, HEURISTIC_PROVIDER)
    assert providers_llm.second_llm(primary).is_heuristic is True
    assert providers_llm.second_llm(SimpleNamespace()) is None, "ohne Tenant keine zweite Instanz"
