"""T2 Provider-Schicht: Anthropic (Tool-Use, Prompt Caching, Batches), claude-cli, Gemini, Kostenbuch, Ergebnis-Cache.

Alles ohne Netz und ohne echte Keys: HTTP über ``httpx.MockTransport``, die CLI über einen Stub."""

from __future__ import annotations

import json

import httpx
import pytest

from chopstr_worker import config, costlog, providers_llm, providers_mm, residency
from chopstr_worker.residency import ResidencyError, Tenant
from chopstr_worker.result_cache import ResultCache

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
STD = Tenant(id="ws", tier="standard", allow_us_subprocessors=True)
NO_CONSENT = Tenant(id="ws-eu", tier="standard")
SOV = Tenant(id="ws-sov", tier="sovereign")


def settings(**kw) -> config.Settings:
    base = {"allow_non_eu_providers": True, "anthropic_api_key": "test-key-nicht-echt"}
    base.update(kw)
    return config.Settings(**base)


def message(tool="answer", inp=None, usage=None) -> dict:
    return {
        "content": [{"type": "tool_use", "name": tool, "input": inp if inp is not None else {"ok": True}}],
        "stop_reason": "tool_use",
        "usage": usage or {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0},
    }


# -- Residency ---------------------------------------------------------------------------------------------
def test_anthropic_provider_needs_opt_in_and_never_sovereign():
    with pytest.raises(ResidencyError):
        residency.assert_allowed("anthropic", STD, config.Settings())
    residency.assert_allowed("anthropic", STD, settings())
    with pytest.raises(ResidencyError):
        residency.assert_allowed("anthropic", SOV, settings())
    with pytest.raises(ResidencyError):
        residency.assert_allowed("claude-cli", STD, config.Settings())
    # Opt-in allein reicht nicht: der Workspace muss US-Unterauftragnehmern zugestimmt haben
    with pytest.raises(ResidencyError, match="nicht zugestimmt"):
        residency.assert_allowed("anthropic", NO_CONSENT, settings())


def test_vertex_only_regions_inside_the_eu():
    off = config.Settings()
    for region in ("europe-west2", "europe-west6"):  # London, Zürich
        with pytest.raises(ResidencyError):
            residency.assert_eu_host(f"https://{region}-aiplatform.googleapis.com/v1/x", off)
        with pytest.raises(ResidencyError):
            providers_mm.select_mm(s=config.Settings(mm_provider="gemini", vertex_project="p", vertex_location=region))
    residency.assert_eu_host("https://europe-west3-aiplatform.googleapis.com/v1/x", off)
    with pytest.raises(ResidencyError, match="nicht zugestimmt"):
        providers_mm.select_mm(NO_CONSENT, s=settings(mm_provider="gemini", gemini_api_key="k"))
    assert providers_mm.select_mm(NO_CONSENT, s=config.Settings(mm_provider="gemini", vertex_project="p", vertex_location="europe-west4")).mode == "vertex"


def test_claude_cli_runs_without_api_key_in_env(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["env"] = kw["env"]

        class P:
            returncode, stdout, stderr = 0, "{}", ""

        return P()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "nicht-echt")
    monkeypatch.setattr(providers_llm.subprocess, "run", fake_run)
    providers_llm.run_cli(["claude"], "p")
    assert "ANTHROPIC_API_KEY" not in seen["env"]


def test_hosts_non_eu_only_with_opt_in_vertex_eu_always():
    off, on = config.Settings(), settings()
    for host in ("https://api.anthropic.com/v1/messages", "https://generativelanguage.googleapis.com/v1beta/models"):
        with pytest.raises(ResidencyError):
            residency.assert_eu_host(host, off)
        residency.assert_eu_host(host, on)
    assert residency.assert_eu_host("https://europe-west4-aiplatform.googleapis.com/v1/x", off) == "europe-west4-aiplatform.googleapis.com"
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://us-central1-aiplatform.googleapis.com/v1/x", on)
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://oauth2.googleapis.com/token", off)
    residency.assert_eu_host("https://oauth2.googleapis.com/token", config.Settings(vertex_project="p"))
    # Opt-in öffnet nur die zwei Anbieter, nicht den Rest der Deny-Liste
    with pytest.raises(ResidencyError):
        residency.assert_eu_host("https://api.openai.com/v1", on)


# -- Modellstufen ------------------------------------------------------------------------------------------
def test_tier_models_defaults_env_and_cli_aliases():
    s = settings()
    assert providers_llm.tier_model("anthropic", "prefilter", s).startswith("claude-haiku")
    assert providers_llm.tier_model("anthropic", "editor", s).startswith("claude-sonnet")
    assert providers_llm.tier_model("anthropic", "judge_escalate", s).startswith("claude-sonnet")
    assert providers_llm.tier_model("anthropic", "judge", settings(model_judge="claude-x")) == "claude-x"
    assert providers_llm.tier_model("claude-cli", "prefilter", s) == "haiku"
    assert providers_llm.tier_model("claude-cli", "editor", settings(model_editor="claude-sonnet-9")) == "sonnet"
    with pytest.raises(ValueError):
        providers_llm.tier_model("anthropic", "boss", s)


# -- Anthropic Messages API --------------------------------------------------------------------------------
def test_anthropic_structured_uses_tool_use_and_cache_blocks():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-key-nicht-echt"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=message())

    ledger = costlog.RunLedger(s=settings())
    llm = providers_llm.LLM(STD, provider="anthropic", s=settings(), tier="prefilter", cost_sink=ledger, transport=httpx.MockTransport(handler))
    out = llm.structured("SYS", "AUFGABE", SCHEMA, "answer", "prefilter_v1", policy_block="RICHTLINIE", cache_prefix="TRANSKRIPT", stage="prefilter")
    assert out == {"ok": True}
    body = seen[0]
    assert body["model"].startswith("claude-haiku")
    assert body["tool_choice"] == {"type": "tool", "name": "answer"}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = body["messages"][0]["content"]
    assert [c["text"] for c in content] == ["RICHTLINIE", "TRANSKRIPT", "AUFGABE"]
    assert [("cache_control" in c) for c in content] == [True, True, False]
    e = ledger.entries[0]
    assert (e["in"], e["cached_in"], e["out"], e["stage"], e["billing"]) == (100, 900, 20, "prefilter", "api")
    # Haiku-Platzhalter: 100 x 1,0 + 900 x 0,1 + 20 x 5,0 je Mio.
    assert e["eur"] == pytest.approx((100 * 1.0 + 900 * 0.1 + 20 * 5.0) / 1e6)


def test_anthropic_missing_tool_output_is_schema_error():
    def handler(request):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hallo"}], "usage": {}})

    llm = providers_llm.LLM(STD, provider="anthropic", s=settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(providers_llm.SchemaError):
        llm.structured("S", "U", SCHEMA, "answer", "p_v1")


def test_anthropic_without_key_fails_loudly():
    llm = providers_llm.LLM(STD, provider="anthropic", s=settings(anthropic_api_key=""), transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.structured("S", "U", SCHEMA, "answer", "p_v1")


def test_result_cache_avoids_second_call(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=message())

    ledger = costlog.RunLedger(s=settings())
    cache = ResultCache(root=tmp_path)
    kw = dict(provider="anthropic", s=settings(), cost_sink=ledger, transport=httpx.MockTransport(handler), result_cache=cache, cache_scope="quelle-1")
    providers_llm.LLM(STD, **kw).structured("S", "U", SCHEMA, "answer", "p_v1", stage="editor")
    providers_llm.LLM(STD, **kw).structured("S", "U", SCHEMA, "answer", "p_v1", stage="editor")
    assert len(calls) == 1
    assert [e["cached_result"] for e in ledger.entries] == [False, True]
    assert ledger.entries[1]["eur"] == 0.0
    # Andere Eingabe, anderer Key
    providers_llm.LLM(STD, **kw).structured("S", "U2", SCHEMA, "answer", "p_v1", stage="editor")
    assert len(calls) == 2


def test_message_batches_submit_poll_collect():
    state = {"polls": 0}
    submitted: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/v1/messages/batches":
            submitted.extend(json.loads(request.content)["requests"])
            return httpx.Response(200, json={"id": "msgbatch_1", "processing_status": "in_progress"})
        if request.method == "GET" and path == "/v1/messages/batches/msgbatch_1":
            state["polls"] += 1
            done = state["polls"] >= 2
            return httpx.Response(200, json={
                "id": "msgbatch_1", "processing_status": "ended" if done else "in_progress",
                "results_url": "https://api.anthropic.com/v1/messages/batches/msgbatch_1/results" if done else None,
            })  # fmt: skip
        if path.endswith("/results"):
            lines = [
                {"custom_id": "r0", "result": {"type": "succeeded", "message": message(inp={"ok": True})}},
                {"custom_id": "r1", "result": {"type": "errored", "error": {"type": "overloaded_error"}}},
            ]
            return httpx.Response(200, text="\n".join(json.dumps(x) for x in lines))
        return httpx.Response(404)

    ledger = costlog.RunLedger(s=settings())
    llm = providers_llm.LLM(STD, provider="anthropic", s=settings(), tier="judge", cost_sink=ledger, transport=httpx.MockTransport(handler))
    items = [
        {"id": "a", "system": "S", "user": "U1", "schema": SCHEMA, "tool_name": "answer", "prompt_version": "judge_clip_v1", "stage": "judge"},
        {"id": "b", "system": "S", "user": "U2", "schema": SCHEMA, "tool_name": "answer", "prompt_version": "judge_clip_v1", "stage": "judge"},
    ]
    sleeps: list[float] = []
    res = llm.structured_many(items, batch=True, poll_s=5, sleep=sleeps.append)
    assert res[0] == {"ok": True}
    assert isinstance(res[1], Exception)
    assert [r["custom_id"] for r in submitted] == ["r0", "r1"]
    assert submitted[0]["params"]["tool_choice"]["name"] == "answer"
    assert sleeps == [5]
    assert ledger.entries[0]["billing"] == "batch"
    full = (100 * 1.0 + 900 * 0.1 + 20 * 5.0) / 1e6
    assert ledger.entries[0]["eur"] == pytest.approx(full * 0.5)


def test_structured_many_without_batch_runs_sequentially():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["messages"][0]["content"][-1]["text"])
        return httpx.Response(200, json=message())

    llm = providers_llm.LLM(STD, provider="anthropic", s=settings(), transport=httpx.MockTransport(handler))
    items = [{"system": "S", "user": u, "schema": SCHEMA, "tool_name": "answer", "prompt_version": "p_v1"} for u in ("a", "b")]
    assert llm.structured_many(items) == [{"ok": True}, {"ok": True}]
    assert calls == ["a", "b"]


# -- claude-cli --------------------------------------------------------------------------------------------
def test_claude_cli_parses_json_and_costs_nothing():
    seen = {}

    def runner(argv, prompt):
        seen["argv"], seen["prompt"] = list(argv), prompt
        inner = 'Hier das Ergebnis:\n```json\n{"ok": true}\n```'
        return json.dumps({"type": "result", "is_error": False, "result": inner, "usage": {"input_tokens": 50, "output_tokens": 5}})

    ledger = costlog.RunLedger(s=settings())
    llm = providers_llm.LLM(STD, provider="claude-cli", s=settings(), tier="prefilter", cost_sink=ledger, cli_runner=runner)
    assert llm.structured("SYS", "AUFGABE", SCHEMA, "answer", "p_v1", cache_prefix="TRANSKRIPT") == {"ok": True}
    assert seen["argv"] == ["claude", "-p", "--model", "haiku", "--output-format", "json"]
    assert "TRANSKRIPT" in seen["prompt"] and "AUFGABE" in seen["prompt"] and '"required"' in seen["prompt"]
    assert ledger.entries[0]["billing"] == "dev_subscription" and ledger.entries[0]["eur"] == 0.0


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"ok": true}\n```',
        "```JSON\n{\"ok\": true}",  # Codeblock ohne schließende Zäune (abgeschnittene Antwort)
        'Ich prüfe {die Spanne} kurz. {"ok": true, "x": {"y": 1}} Fertig {sonst nichts}.',
        '{"beispiel": 1} und die Antwort: {"ok": false}',
    ],
)
def test_extract_json_object_is_robust(raw):
    out = providers_llm.extract_json_object(raw, required=["ok"])
    assert "ok" in out


def test_parse_cli_output_envelopes():
    usage = {"input_tokens": 3, "output_tokens": 2, "cache_creation_input_tokens": 40}
    as_list = json.dumps([{"type": "system"}, {"type": "result", "is_error": False, "result": 'Ok: {"ok": true}', "usage": usage}])
    out, u = providers_llm.parse_cli_output(as_list, ["ok"])
    assert out == {"ok": True} and u["cache_write"] == 40
    out, _ = providers_llm.parse_cli_output(json.dumps({"type": "result", "result": {"ok": True}}), ["ok"])
    assert out == {"ok": True}
    out, _ = providers_llm.parse_cli_output(json.dumps({"type": "result", "result": "x", "structured_output": {"ok": True}}), ["ok"])
    assert out == {"ok": True}
    out, _ = providers_llm.parse_cli_output('kein JSON, aber {"ok": true}', ["ok"])
    assert out == {"ok": True}
    with pytest.raises(providers_llm.SchemaError) as exc:
        providers_llm.parse_cli_output(json.dumps({"type": "result", "result": "nur Text", "usage": usage}))
    assert exc.value.usage["out"] == 2


def test_claude_cli_retries_once_with_correction_hint():
    prompts_seen = []

    def runner(argv, prompt):
        prompts_seen.append(prompt)
        inner = "Ich kann das so nicht beantworten." if len(prompts_seen) == 1 else '{"ok": true}'
        return json.dumps({"type": "result", "result": inner, "usage": {"input_tokens": 10, "output_tokens": 4}})

    ledger = costlog.RunLedger(s=settings())
    llm = providers_llm.LLM(STD, provider="claude-cli", s=settings(), cost_sink=ledger, cli_runner=runner)
    assert llm.structured("S", "U", SCHEMA, "answer", "p_v1", stage="editor") == {"ok": True}
    assert len(prompts_seen) == 2 and "nicht verwendbar" in prompts_seen[1] and "ok" in prompts_seen[1]
    assert len(ledger.entries) == 2 and ledger.entries[0]["out"] == 4  # gescheiterter Versuch zählt mit

    calls = []

    def always_bad(argv, prompt):
        calls.append(1)
        return json.dumps({"type": "result", "result": "nie JSON"})

    llm = providers_llm.LLM(STD, provider="claude-cli", s=settings(), cli_runner=always_bad)
    with pytest.raises(providers_llm.SchemaError):
        llm.structured("S", "U", SCHEMA, "answer", "p_v1")
    assert len(calls) == 2  # genau ein Wiederholversuch


def test_anthropic_text_fallback_and_retry():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(200, json={"content": [{"type": "text", "text": "Kurz gesagt"}], "stop_reason": "end_turn", "usage": {}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": 'Hier: ```json\n{"ok": true}\n```'}], "stop_reason": "end_turn", "usage": {}})

    llm = providers_llm.LLM(STD, provider="anthropic", s=settings(), transport=httpx.MockTransport(handler))
    assert llm.structured("S", "U", SCHEMA, "answer", "p_v1") == {"ok": True}
    assert len(bodies) == 2 and "nicht verwendbar" in bodies[1]["messages"][0]["content"][-1]["text"]


def test_claude_cli_never_in_production():
    with pytest.raises(ResidencyError):
        providers_llm.LLM(STD, provider="claude-cli", s=settings(app_env="production"), cli_runner=lambda a, p: "{}")


def test_claude_cli_error_result_raises():
    runner = lambda a, p: json.dumps({"is_error": True, "result": "Limit erreicht"})  # noqa: E731
    llm = providers_llm.LLM(STD, provider="claude-cli", s=settings(), cli_runner=runner)
    with pytest.raises(RuntimeError, match="Fehler"):
        llm.structured("S", "U", SCHEMA, "answer", "p_v1")


# -- Kostenbuch ----------------------------------------------------------------------------------------------
def test_price_table_prefix_env_override_and_fallback():
    s = settings(price_table_json='{"claude-haiku-5": {"in": 2.0, "out": 8.0}}')
    assert costlog.price_for("claude-haiku-5-5", s)["in"] == 2.0
    assert costlog.price_for("claude-haiku-5-5", s)["cached_in"] == pytest.approx(0.2)
    assert costlog.price_for("claude-sonnet-5-5", s)["out"] == 15.0
    assert costlog.price_for("unbekannt", config.Settings(llm_eur_per_1m_input=7.0))["in"] == 7.0
    with pytest.raises(ValueError):
        costlog.price_table(settings(price_table_json="{kaputt"))


def test_ledger_budget_skips_and_reports_per_source_hour():
    ledger = costlog.RunLedger(budget_eur=0.001, s=settings())
    ledger.check("prefilter")
    ledger({"stage": "prefilter", "model": "claude-sonnet-5-5", "in": 1000, "out": 100})  # 0,0045 EUR
    with pytest.raises(costlog.BudgetExceeded):
        ledger.check("editor")
    summary = ledger.summary(source_seconds=1800)
    assert summary["skipped"][0]["stage"] == "editor"
    assert summary["eur_per_source_hour"] == pytest.approx(ledger.eur * 2, rel=1e-3)
    assert summary["tokens_per_source_hour"] == pytest.approx(2200.0)
    assert summary["by_stage"]["prefilter"]["calls"] == 1
    tok = costlog.RunLedger(budget_tokens=10, s=settings())
    tok({"stage": "x", "model": "m", "in": 11})
    with pytest.raises(costlog.BudgetExceeded):
        tok.check("y")


# -- Multimodal ------------------------------------------------------------------------------------------------
def test_select_mm_defaults_to_none_and_guards_gemini():
    assert providers_mm.select_mm(s=config.Settings()).name == "none"
    with pytest.raises(ResidencyError):
        providers_mm.select_mm(s=config.Settings(mm_provider="gemini", gemini_api_key="k"))
    with pytest.raises(ResidencyError):
        providers_mm.select_mm(SOV, s=settings(mm_provider="gemini", gemini_api_key="k"))
    with pytest.raises(ResidencyError):
        providers_mm.select_mm(s=config.Settings(mm_provider="gemini", vertex_project="p", vertex_location="us-central1"))
    v = providers_mm.select_mm(s=config.Settings(mm_provider="gemini", vertex_project="p", vertex_location="europe-west4"))
    assert v.mode == "vertex" and "europe-west4-aiplatform.googleapis.com" in v.endpoint()


def test_mock_mm_returns_window_relative_events():
    mm = providers_mm.MockMM(events=[{"t_start": 65.0, "t_end": 67.0, "type": "laughter", "intensity": 0.8}])
    assert mm.scan_window("x.mp4", 60, 120, "p")["events"][0]["t_start"] == pytest.approx(5.0)
    assert mm.scan_window("x.mp4", 0, 60, "p")["events"] == []


def test_gemini_aistudio_request_and_usage(tmp_path):
    clip = tmp_path / "w.mp4"
    clip.write_bytes(b"\x00" * 64)
    seen = {}

    def handler(request):
        seen["url"], seen["body"], seen["key"] = str(request.url), json.loads(request.content), request.headers.get("x-goog-api-key")
        text = json.dumps({"events": [{"t_start": 1, "t_end": 2, "type": "shout", "intensity": 0.9}]})
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 40, "cachedContentTokenCount": 200},
        })  # fmt: skip

    ledger = costlog.RunLedger(s=settings())
    s = settings(mm_provider="gemini", gemini_api_key="g-test")
    mm = providers_mm.GeminiMM(s, cost_sink=ledger, transport=httpx.MockTransport(handler))
    out = mm.scan_window(clip, 0, 600, "PROMPT")
    assert out["events"][0]["type"] == "shout"
    assert seen["url"].endswith("/v1beta/models/gemini-2.5-flash:generateContent") and seen["key"] == "g-test"
    gc = seen["body"]["generationConfig"]
    assert gc["responseMimeType"] == "application/json" and gc["responseSchema"]["type"] == "OBJECT"
    assert "minimum" not in json.dumps(gc["responseSchema"])
    assert (ledger.entries[0]["in"], ledger.entries[0]["cached_in"], ledger.entries[0]["out"]) == (1000, 200, 40)
    assert ledger.entries[0]["stage"] == "mm_scan"


def test_gemini_rejects_too_large_inline(tmp_path, monkeypatch):
    clip = tmp_path / "w.mp4"
    clip.write_bytes(b"\x00" * 128)
    monkeypatch.setattr(providers_mm, "MAX_INLINE_BYTES", 64)
    mm = providers_mm.GeminiMM(settings(gemini_api_key="g"), transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ValueError, match="inline"):
        mm.scan_window(clip, 0, 10, "p")


def test_cli_runs_carry_api_equivalent_and_token_note():
    ledger = costlog.RunLedger(s=settings())
    ledger({"stage": "editor", "model": "sonnet", "billing": "dev_subscription", "in": 1000, "cached_in": 10_000,
            "cache_write": 40_000, "out": 2_000})  # fmt: skip
    ledger({"stage": "prefilter", "model": "haiku", "billing": "dev_subscription", "in": 1000, "out": 1000})
    ledger({"stage": "x", "model": "heuristic-v1", "billing": "local", "in": 1000})
    s = ledger.summary(3600.0)
    assert s["eur"] == 0.0
    sonnet = (1000 * 3.0 + 10_000 * 0.30 + 40_000 * 3.75 + 2_000 * 15.0) / 1e6
    haiku = (1000 * 1.0 + 1000 * 5.0) / 1e6
    assert s["eur_api_equivalent"] == pytest.approx(sonnet + haiku)
    assert s["by_stage"]["editor"]["eur_api_equivalent"] == pytest.approx(sonnet)
    assert s["eur_api_equivalent_per_source_hour"] == pytest.approx(sonnet + haiku, abs=1e-4)
    assert s["notes"] and "Systemprompt" in s["notes"][0]
    api = costlog.RunLedger(s=settings())
    api({"stage": "editor", "model": "claude-sonnet-5-5", "in": 1000, "out": 100})
    assert api.summary()["eur_api_equivalent"] == api.summary()["eur"] and api.summary()["notes"] == []


def test_claude_cli_extra_args_from_env_setting():
    seen = {}

    def runner(argv, prompt):
        seen["argv"] = list(argv)
        return json.dumps({"type": "result", "result": '{"ok": true}'})

    s = settings(claude_cli_args="--flag-a 'wert mit leerzeichen'")
    providers_llm.LLM(STD, provider="claude-cli", s=s, cli_runner=runner).structured("S", "U", SCHEMA, "answer", "p_v1")
    assert seen["argv"][-2:] == ["--flag-a", "wert mit leerzeichen"]
