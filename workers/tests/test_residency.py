"""Beweise für den Residency-Guard: kein Aufruf außerhalb der EU."""

from __future__ import annotations

import httpx
import pytest

from chopstr_worker import config, providers_llm, residency
from chopstr_worker.residency import ResidencyError, Tenant


def test_a_sovereign_tenant_may_not_use_bedrock():
    sov = Tenant(id="ws-sov", tier="sovereign")
    with pytest.raises(ResidencyError):
        residency.assert_allowed("bedrock-eu", sov)
    residency.assert_allowed("mistral-eu", sov)
    residency.assert_allowed("selfhost-eu", sov)
    std = Tenant(id="ws-std", tier="standard")
    residency.assert_allowed("bedrock-eu", std)
    with pytest.raises(ResidencyError):
        residency.assert_allowed("openai-us", std)


def test_a2_llm_class_never_selects_bedrock_for_sovereign(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock-eu")
    monkeypatch.setenv("MISTRAL_MODEL", "m")
    config.reload()
    llm = providers_llm.LLM(Tenant(id="ws", tier="sovereign"))
    assert llm.provider in residency.NON_US_CHAIN
    with pytest.raises(ResidencyError):
        providers_llm.LLM(Tenant(id="ws", tier="sovereign"), provider="bedrock-eu")


def test_b_assert_eu_host_blocks_openai():
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://api.openai.com/v1/chat/completions")
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://bedrock-runtime.us-east-1.amazonaws.com")
    assert residency.assert_eu_host("https://bedrock-runtime.eu-central-1.amazonaws.com") == "bedrock-runtime.eu-central-1.amazonaws.com"
    assert residency.assert_eu_host("https://api.mistral.ai/v1/chat/completions") == "api.mistral.ai"
    assert residency.assert_eu_host("http://localhost:9000/bucket") == "localhost"
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("not a url")


def test_c_guarded_client_blocks_before_network():
    calls: list[str] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(transport_handler)
    with residency.guarded_client(transport=transport) as client:
        with pytest.raises(ResidencyError):
            client.get("https://api.openai.com/v1/models")
        assert calls == []  # der Transport wurde nie erreicht
        r = client.get("https://api.mistral.ai/v1/models")
        assert r.status_code == 200
        assert calls == ["https://api.mistral.ai/v1/models"]


async def test_c2_guarded_async_client_blocks():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    async with residency.guarded_async_client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ResidencyError):
            await client.get("https://example.com")
        assert calls == []


def test_d_egress_allowlist_applies(monkeypatch):
    monkeypatch.setenv("EGRESS_ALLOWLIST", "")
    config.reload()
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://asr.example-eu.de/v1")
    monkeypatch.setenv("EGRESS_ALLOWLIST", "asr.example-eu.de, https://tool.intern.at:8443/pfad")
    config.reload()
    assert residency.assert_eu_host("https://asr.example-eu.de/v1") == "asr.example-eu.de"
    assert residency.assert_eu_host("https://tool.intern.at:8443/x") == "tool.intern.at"
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://api.openai.com")


def test_deny_list_beats_configuration(monkeypatch):
    monkeypatch.setenv("EGRESS_ALLOWLIST", "api.openai.com, bedrock-runtime.us-east-1.amazonaws.com")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://api.anthropic.com")
    config.reload()
    for url in ("https://api.openai.com/v1", "https://bedrock-runtime.us-east-1.amazonaws.com", "https://api.anthropic.com/v1"):
        with pytest.raises(ResidencyError, match="gesperrt"):
            residency.assert_eu_host(url)
    assert residency.host_denied("generativelanguage.googleapis.com")
    assert not residency.host_denied("bedrock-runtime.eu-central-1.amazonaws.com")


def test_configured_hosts_are_allowed(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT", "https://s3.eu-central-1.hetzner.example")
    monkeypatch.setenv("LANGUAGETOOL_URL", "http://lt.intern:8010/v2")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal.intern:7233")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://llm.intern/v1")
    monkeypatch.setenv("GLADIA_BASE_URL", "https://gladia.eu.example")
    config.reload()
    hosts = residency.allowed_hosts()
    for h in ("s3.eu-central-1.hetzner.example", "lt.intern", "temporal.intern", "llm.intern", "gladia.eu.example", "api.mistral.ai"):
        assert h in hosts


def test_llm_structured_uses_guard_for_selfhost(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "selfhost-eu")
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://llm.intern")
    monkeypatch.setenv("SELFHOST_LLM_MODEL", "local-model")
    config.reload()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    real = residency.guarded_client

    def patched(s=None, **kw):
        return real(s, transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(residency, "guarded_client", patched)
    costs = []
    llm = providers_llm.LLM(Tenant(id="ws", tier="sovereign"), cost_sink=costs.append)
    out = llm.structured("sys", "user", {"type": "object", "required": ["x"]}, "tool", "p_v1")
    assert out == {"x": 1}
    assert seen == ["https://llm.intern/v1/chat/completions"]
    assert costs and costs[0]["in"] == 3 and costs[0]["provider"] == "selfhost-eu"

    # Nicht erlaubter Host: bricht ab, bevor der Transport erreicht wird
    monkeypatch.setenv("SELFHOST_LLM_BASE_URL", "https://api.openai.com")
    config.reload()
    seen.clear()
    with pytest.raises(ResidencyError):
        providers_llm.LLM(Tenant(id="ws", tier="sovereign")).structured("s", "u", {"type": "object"}, "t", "p_v1")
    assert seen == []
