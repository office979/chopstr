"""Copy-Engine: fünf Varianten, Linter, Claim-Check, Auswahlregel, Post-Captions, LanguageTool nur mit URL."""

from __future__ import annotations

import pytest

from chopstr_worker import config, heuristic_llm, providers_llm, residency
from chopstr_worker.pipeline import copy_de, copy_engine
from chopstr_worker.providers_llm import LLM
from chopstr_worker.residency import Tenant

CLIP = (
    "Ehrlich gesagt war das der teuerste Fehler meiner Karriere. Wir haben 40 Prozent Marge verloren, "
    "aber das gilt nicht für jede Firma. Der Grund war ein falsches Preismodell."
)


class FakeLLM:
    """Gibt vorbereitete Antworten pro Tool zurück und zeichnet die Aufrufe auf."""

    def __init__(self, hooks: dict, caption: dict | None = None, model_id: str = "fake-model"):
        self.hooks, self.caption, self.model_id = hooks, caption or {"text": "Post.", "cta": "Was meinst du?"}, model_id
        self.calls: list[tuple[str, str]] = []
        self.provider = "selfhost-eu"

    def model(self) -> str:
        return self.model_id

    def structured(self, system, user, schema, tool_name, prompt_version, job_type="llm_score"):
        self.calls.append((tool_name, prompt_version))
        assert set(schema["required"]) <= (set(self.hooks) if tool_name == "write_hooks" else set(self.caption))
        return self.hooks if tool_name == "write_hooks" else dict(self.caption)


def _variants(*spoken: str) -> dict:
    patterns = list(copy_engine.HOOK_PATTERNS)
    return {"variants": [{"pattern": patterns[i], "spoken": s, "onscreen": s} for i, s in enumerate(spoken)]}


def _heuristic() -> LLM:
    return LLM(Tenant(id="ws"), provider=providers_llm.HEURISTIC_PROVIDER, s=config.settings())


def test_heuristic_yields_five_variants_within_limits_and_row_shape():
    brand = copy_de.BrandProfile(address="sie", country="AT", platform="linkedin")
    res = copy_engine.write_copy(_heuristic(), CLIP, brand)
    assert len(res.variants) == 5
    assert [v["pattern"] for v in res.variants] == list(copy_engine.HOOK_PATTERNS)
    for v in res.variants:
        assert copy_engine.word_count(v["spoken"]) <= copy_engine.SPOKEN_MAX_WORDS
        assert copy_engine.word_count(v["onscreen"]) <= copy_engine.ONSCREEN_MAX_WORDS
        assert v["claim_issues"] == []  # Heuristik erfindet keine Zahlen
        assert set(v) == {"pattern", "spoken", "onscreen", "lint_notes", "claim_issues"}
    assert res.spoken_hook == res.variants[0]["spoken"] and res.pattern == "identity_call"
    assert set(res.post_captions) == set(copy_engine.PLATFORMS)
    assert res.cta and res.model_id == heuristic_llm.MODEL_ID and res.prompt_version == "hooks_v1"
    assert res.post_caption_prompt_version == "post_caption_v1"
    row = res.to_row()
    assert set(row) == {"spoken_hook", "onscreen_hook", "pattern", "variants", "post_captions", "cta", "lint_notes", "claim_issues", "model_id", "prompt_version"}
    assert "Sie" in res.cta  # Anrede aus dem Prompt gelesen
    assert res.languagetool is None


def test_claim_issue_for_invented_number_and_selection_rule():
    llm = FakeLLM(_variants("Wir haben 90 Prozent verloren", "Der Grund war ein falsches Preismodell", "x", "y", "z"))
    res = copy_engine.write_copy(llm, CLIP, copy_de.BrandProfile(), platforms=("linkedin",))
    assert any("90" in c for c in res.variants[0]["claim_issues"])
    assert res.spoken_hook == "Der Grund war ein falsches Preismodell" and res.pattern == "contrarian"
    assert res.claim_issues == []  # gewählte Variante ohne Issues, Posts sauber
    assert [c[0] for c in llm.calls] == ["write_hooks", "write_post_caption"]


def test_all_variants_with_issues_falls_back_to_first_and_keeps_issues():
    llm = FakeLLM(_variants("Garantiert 100 % Erfolg", "Immer 99 Prozent", "1", "2", "3"))
    res = copy_engine.write_copy(llm, CLIP, copy_de.BrandProfile(), platforms=("tiktok",))
    assert res.spoken_hook == "Garantiert 100 % Erfolg" and res.pattern == "identity_call"
    assert res.claim_issues


def test_lint_notes_word_limits_and_address():
    long_spoken = " ".join(["Wort"] * 13)
    llm = FakeLLM(_variants(long_spoken, "Das solltest du wissen", "a", "b", "c"))
    res = copy_engine.write_copy(llm, CLIP, copy_de.BrandProfile(address="sie"), platforms=("linkedin",))
    v0, v1 = res.variants[0], res.variants[1]
    assert any("zu lang" in n for n in v0["lint_notes"])
    assert any("Du-Form in Sie-Profil" in n for n in v1["lint_notes"])
    assert any("zu lang" in n for n in res.lint_notes)


def test_post_captions_per_platform_and_hook_repetition_note():
    llm = FakeLLM(_variants("Hook A", "b", "c", "d", "e"), caption={"text": "Hook A wörtlich wiederholt.", "cta": "Sag was."})
    res = copy_engine.write_copy(llm, CLIP, copy_de.BrandProfile(platform="reels"))
    assert [c[0] for c in llm.calls].count("write_post_caption") == 4
    assert set(res.post_captions) == {"tiktok", "reels", "shorts", "linkedin"}
    assert any("wiederholt den On-Screen-Hook" in n for n in res.lint_notes)
    assert res.cta == "Sag was."


def test_languagetool_only_with_url_and_via_residency_hook(monkeypatch):
    monkeypatch.delenv("LANGUAGETOOL_URL", raising=False)
    config.reload()
    calls: list = []

    def fake_client(s=None, **kw):
        calls.append(("client", kw))
        raise AssertionError("ohne LANGUAGETOOL_URL darf kein Client entstehen")

    monkeypatch.setattr(residency, "guarded_client", fake_client)
    llm = FakeLLM(_variants("a", "b", "c", "d", "e"))
    res = copy_engine.write_copy(llm, CLIP, copy_de.BrandProfile(), platforms=("linkedin",))
    assert calls == [] and res.languagetool is None

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"matches": [{"message": "Komma fehlt", "rule": {"id": "KOMMA"}, "context": {"text": "a b", "offset": 0, "length": 1}}]}

    class FakeClient:
        def __init__(self, s, **kw):
            self.posted: list = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, **kw):
            residency.assert_eu_host(url, config.settings())  # wie der echte Hook: Host muss erlaubt sein
            calls.append(("post", url, data))
            return FakeResponse()

    monkeypatch.setattr(residency, "guarded_client", lambda s=None, **kw: FakeClient(s, **kw))
    monkeypatch.setenv("LANGUAGETOOL_URL", "http://localhost:8010/v2")
    config.reload()
    res = copy_engine.write_copy(llm, CLIP, copy_de.BrandProfile(country="CH"), platforms=("linkedin",))
    posts = [c for c in calls if c[0] == "post"]
    assert posts and all(c[1] == "http://localhost:8010/v2/check" for c in posts)
    assert all(c[2]["language"] == "de-CH" for c in posts)
    assert any(n.startswith("LanguageTool (hook): Komma fehlt") for n in res.lint_notes)
    assert res.languagetool == {"url": "http://localhost:8010/v2", "locale": "de-CH", "notes": len(posts)}


def test_languagetool_errors_are_notes_not_exceptions(monkeypatch):
    monkeypatch.setenv("LANGUAGETOOL_URL", "https://api.openai.com/v2")  # Deny-Liste hat Vorrang
    config.reload()
    notes = copy_engine.languagetool_check("Ein Text.", "DE", config.settings(), "hook")
    assert len(notes) == 1 and notes[0].startswith("LanguageTool (hook): nicht erlaubt")

    def boom(s=None, **kw):
        raise ConnectionError("down")

    monkeypatch.setattr(residency, "guarded_client", boom)
    monkeypatch.setenv("LANGUAGETOOL_URL", "http://localhost:8010")
    config.reload()
    notes = copy_engine.languagetool_check("Ein Text.", "AT", config.settings())
    assert notes == ["LanguageTool: nicht erreichbar (ConnectionError)"]


def test_empty_variants_fail_clearly():
    with pytest.raises(RuntimeError, match="keine Hook-Varianten"):
        copy_engine.write_copy(FakeLLM({"variants": []}), CLIP, copy_de.BrandProfile(), platforms=("linkedin",))
