"""LLM-Schicht, provider-unabhängig (aus dem Gerüst, mit Residency-Guard auf Host-Ebene).

  STANDARD   -> Claude über AWS Bedrock, EU-Inference-Profil (bedrock-eu)
  SOVEREIGN  -> Mistral über EU-Endpoint (mistral-eu) oder selbst gehostetes Open-Weight-Modell
                mit OpenAI-kompatiblem Endpoint (selfhost-eu). Kein US-Anbieter in der Kette.
  ENTWICKLUNG -> ``local-heuristic``: deterministische Heuristik ohne Netz (``heuristic_llm``),
                Modell-ID ``heuristic-v1``. Kein Ersatz für ein Sprachmodell, nur für Entwicklung und Demo.

- ``residency.assert_allowed`` prüft den Provider gegen den Tenant.
- ``residency.assert_eu_host`` prüft VOR JEDEM Aufruf den Zielhost; HTTP läuft über ``guarded_client``.
- Cache in Redis optional: Key = (provider, model, prompt_version, input_hash).
- ``cost_sink`` bekommt Tokenzahlen pro Aufruf (für ``job_costs``).
- Modell-IDs kommen ausschließlich aus ENV (BEDROCK_MODEL_ID, MISTRAL_MODEL, SELFHOST_LLM_MODEL).

Mehrstufige Engine und Trainingsschleife (T2):

  ANTHROPIC   -> ``anthropic``: Messages API direkt (``ANTHROPIC_API_KEY``), strukturierte Ausgabe per
                erzwungenem Tool-Use, Prompt Caching (``cache_control`` auf System-Prompt, Richtlinienblock
                und Transkript-Präfix) und Message Batches für nicht dringende Eval- und Trainingsläufe
                (``AnthropicBatch``, ``LLM.structured_many(batch=True)``). Kein EU-Anbieter: nur mit
                ``CHOPSTR_ALLOW_NON_EU_PROVIDERS=1``.
  CLAUDE-CLI  -> ``claude-cli``: nur Entwicklung und der erste Testlauf ohne Key. Ruft
                ``claude -p --model <alias> --output-format json`` auf, Kosten 0 € mit Kennzeichnung
                ``dev_subscription``. Unter ``APP_ENV=production`` gesperrt.

- Modell-Stufen (``tier``): ``prefilter``, ``editor``, ``judge``, ``judge_escalate`` aus
  ``CHOPSTR_MODEL_PREFILTER`` usw.; ohne Wert ``DEFAULT_TIER_MODELS`` (Anthropic) bzw. die CLI-Aliase.
- ``result_cache`` (``result_cache.ResultCache``): Ergebnis je Quelle, Stufe und Eingabe-Hash, damit ein
  zweiter Lauf nichts doppelt rechnet; ein Treffer geht mit ``cached_result`` und 0 € ins Kostenbuch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any

from . import config, residency
from .residency import EU_OK, NON_US_CHAIN, ResidencyError, Tenant, assert_allowed

log = logging.getLogger("chopstr.llm")

CACHE_TTL_S = 60 * 60 * 24 * 30
HEURISTIC_PROVIDER = "local-heuristic"
HEURISTIC_MODEL_ID = "heuristic-v1"
ANTHROPIC_PROVIDER = "anthropic"
CLAUDE_CLI_PROVIDER = "claude-cli"
ANTHROPIC_VERSION = "2023-06-01"
TIERS = ("prefilter", "editor", "judge", "judge_escalate")
# Standard je Stufe für die Anthropic-API: billig für Vorfilter und Richter, stark für Schnitt und Copy.
DEFAULT_TIER_MODELS = {
    "prefilter": "claude-haiku-5-5",
    "editor": "claude-sonnet-5-5",
    "judge": "claude-haiku-5-5",
    "judge_escalate": "claude-sonnet-5-5",
}
CLI_TIER_ALIASES = {"prefilter": "haiku", "editor": "sonnet", "judge": "haiku", "judge_escalate": "sonnet"}
CLI_ALIASES = frozenset({"haiku", "sonnet", "opus"})
CLI_TIMEOUT_S = 600


class SchemaError(RuntimeError):
    """Antwort entspricht nicht dem Tool-Schema. ``usage`` trägt die Tokens des gescheiterten Aufrufs (fürs
    Kostenbuch); ``structured`` versucht es bei CLI und Anthropic genau einmal mit Korrekturhinweis."""

    def __init__(self, message: str, usage: dict[str, Any] | None = None):
        super().__init__(message)
        self.usage = dict(usage or {})


# Ein Wiederholversuch nach unlesbarer Antwort: CLI ohne Schema-Zwang und Anthropic ohne Tool-Block.
SCHEMA_RETRY_PROVIDERS = frozenset({"anthropic", "claude-cli"})
CORRECTION_HINT = (
    "Deine letzte Antwort war nicht verwendbar ({error}). Antworte jetzt ausschließlich mit genau einem JSON-Objekt "
    "nach dem Schema, ohne Text davor oder danach und ohne Codeblock. Alle Pflichtfelder müssen vorhanden sein: {required}."
)


def cache_key(provider: str, model: str, prompt_version: str, payload: Any) -> str:
    raw = json.dumps([provider, model, prompt_version, payload], sort_keys=True, ensure_ascii=False)
    return "llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tier_model(provider: str, tier: str | None, s: config.Settings | None = None) -> str:
    """Modell einer Stufe: ENV (``CHOPSTR_MODEL_<STUFE>``), sonst Standard je Provider.

    Für ``claude-cli`` zählen nur die Aliase ``haiku``, ``sonnet``, ``opus``; eine volle Modell-ID aus der
    ENV wird dort durch den Alias der Stufe ersetzt (die CLI läuft über ein Abo, nicht über die API)."""
    s = s or config.settings()
    tier = tier or "editor"
    if tier not in TIERS:
        raise ValueError(f"Unbekannte Modellstufe {tier!r}, erlaubt: {', '.join(TIERS)}")
    env = {"prefilter": s.model_prefilter, "editor": s.model_editor, "judge": s.model_judge, "judge_escalate": s.model_judge_escalate}[tier]
    if provider == CLAUDE_CLI_PROVIDER:
        return env if env in CLI_ALIASES else CLI_TIER_ALIASES[tier]
    return env or DEFAULT_TIER_MODELS[tier]


def full_user_text(user: str, policy_block: str | None = None, cache_prefix: str | None = None) -> str:
    """Nutzertext für Provider ohne Cache-Blöcke: Richtlinie, Transkript-Präfix, eigentliche Aufgabe."""
    return "\n\n".join(x for x in (policy_block, cache_prefix, user) if x)


def anthropic_params(
    system: str,
    user: str,
    schema: dict,
    tool_name: str,
    model: str,
    max_tokens: int,
    temperature: float,
    policy_block: str | None = None,
    cache_prefix: str | None = None,
) -> dict[str, Any]:
    """Request-Körper der Messages API: Tool erzwungen, Cache-Marken auf den stabilen Teilen.

    Reihenfolge der Cache-Punkte (höchstens vier erlaubt, hier drei): System-Prompt, Richtlinien- bzw.
    SOP-Block, Transkript-Präfix. Alles davor ist bei gleichen Eingaben byte-gleich und wird ab dem zweiten
    Aufruf aus dem Cache gelesen; nur die Aufgabe am Ende ist neu. Zu kurze Blöcke cacht die API nicht,
    das kostet nichts extra."""
    ephemeral = {"type": "ephemeral"}
    content: list[dict[str, Any]] = []
    for block in (policy_block, cache_prefix):
        if block:
            content.append({"type": "text", "text": block, "cache_control": ephemeral})
    content.append({"type": "text", "text": user})
    return {
        "model": model,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "system": [{"type": "text", "text": system, "cache_control": ephemeral}],
        "messages": [{"role": "user", "content": content}],
        "tools": [{"name": tool_name, "description": f"Antwort als {tool_name}", "input_schema": schema}],
        "tool_choice": {"type": "tool", "name": tool_name},
    }


def parse_anthropic_message(msg: dict[str, Any], tool_name: str | None = None) -> tuple[dict, dict[str, int]]:
    """Tool-Eingabe und Tokens aus einer Messages-Antwort. ``in`` sind die nicht gecachten Eingabetokens."""
    blocks = msg.get("content") or []
    out = next(
        (b.get("input") for b in blocks if b.get("type") == "tool_use" and (tool_name is None or b.get("name") == tool_name)),
        None,
    )
    usage = _usage_from(msg.get("usage") or {})
    if out is None:
        # Rückfall: kein Tool-Block (z. B. Text-Antwort bei max_tokens oder ohne Tool-Zwang). Dann gilt das
        # gleiche Parsing wie für die CLI: JSON aus dem Text, auch in einem Codeblock oder mit Vor- und Nachtext.
        text = "\n".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
        try:
            out = extract_json_object(text)
        except SchemaError:
            raise SchemaError(f"Kein Tool-Output vom Modell erhalten (stop_reason={msg.get('stop_reason')})", usage) from None
    return out, usage


def _usage_from(u: dict[str, Any]) -> dict[str, int]:
    """Tokens aus einem ``usage``-Block der Messages API bzw. der CLI-Hülle (gleiche Feldnamen)."""
    return {
        "in": int(u.get("input_tokens", 0) or 0),
        "cached_in": int(u.get("cache_read_input_tokens", 0) or 0),
        "cache_write": int(u.get("cache_creation_input_tokens", 0) or 0),
        "out": int(u.get("output_tokens", 0) or 0),
    }


_JSON_FENCE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)(?:```|\Z)", re.DOTALL)


def _json_objects(text: str) -> list[dict]:
    """Alle JSON-Objekte im Text, von links nach rechts (``raw_decode`` ab jeder ``{``; verschachtelte zählen
    nicht doppelt). Klammern in Prosa davor oder danach stören so nicht mehr."""
    dec = json.JSONDecoder()
    found: list[dict] = []
    i, n = 0, len(text)
    while i < n:
        a = text.find("{", i)
        if a < 0:
            break
        try:
            obj, end = dec.raw_decode(text, a)
        except json.JSONDecodeError:
            i = a + 1
            continue
        if isinstance(obj, dict):
            found.append(obj)
        i = end
    return found


def extract_json_object(text: Any, required: Sequence[str] = ()) -> dict:
    """JSON-Objekt aus einem Modelltext: direkt, in einem Codeblock (auch ohne schließende Zäune) oder mit Vor- und
    Nachtext. Mit ``required`` gewinnt das erste Objekt, das alle Pflichtfelder hat, sonst das größte."""
    if isinstance(text, dict):
        return text
    text = str(text or "").strip()
    found: list[dict] = []
    for cand in [m.group(1).strip() for m in _JSON_FENCE.finditer(text)] + [text]:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            found.extend(_json_objects(cand))
            continue
        if isinstance(obj, dict):
            found.append(obj)
    if not found:
        raise SchemaError("Antwort enthält kein JSON-Objekt")
    req = [k for k in required]
    full = [o for o in found if all(k in o for k in req)]
    if full:
        return full[0]
    return max(found, key=lambda o: len(json.dumps(o, ensure_ascii=False)))


def parse_cli_output(raw: str, required: Sequence[str] = ()) -> tuple[dict, dict[str, int]]:
    """Antwort von ``claude -p --output-format json``: Hülle als Objekt (``result``, ``usage``) oder als Liste von
    Ereignissen (dann zählt das letzte ``type: result``). ``structured_output`` geht vor ``result``; ``result`` darf
    Text mit JSON oder schon ein Objekt sein. Ohne lesbare Hülle wird der rohe Text nach JSON durchsucht."""
    try:
        outer: Any = json.loads(raw)
    except json.JSONDecodeError:
        return extract_json_object(raw, required), {}
    if isinstance(outer, list):
        results = [e for e in outer if isinstance(e, dict) and e.get("type") == "result"]
        outer = results[-1] if results else next((e for e in reversed(outer) if isinstance(e, dict)), None)
    if not isinstance(outer, dict):
        raise SchemaError("Claude-CLI lieferte kein JSON-Objekt")
    usage = _usage_from(outer.get("usage") or {})
    if outer.get("is_error"):
        raise RuntimeError(f"Claude-CLI meldet einen Fehler: {str(outer.get('result') or '')[:300]}")
    if "result" not in outer and "structured_output" not in outer and "type" not in outer:
        return outer, usage  # die Hülle ist schon die Antwort
    body = outer.get("structured_output") if isinstance(outer.get("structured_output"), dict) else outer.get("result", "")
    try:
        return extract_json_object(body, required), usage
    except SchemaError as exc:
        raise SchemaError(str(exc), usage) from None


def run_cli(argv: Sequence[str], prompt: str, timeout_s: float = CLI_TIMEOUT_S) -> str:
    """Startet die Claude-CLI mit dem Prompt auf stdin (kein Längenlimit der Kommandozeile)."""
    # Ohne API-Key in der Umgebung: die CLI läuft über das Abo; mit Key würde sie still über die API abrechnen,
    # und das Kostenbuch zeigte trotzdem 0 € (dev_subscription).
    import os

    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    try:
        proc = subprocess.run(list(argv), input=prompt, capture_output=True, text=True, timeout=timeout_s, check=False, env=env)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Claude-CLI nicht gefunden ({argv[0]}); CHOPSTR_CLAUDE_CLI setzen oder installieren") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"Claude-CLI beendet mit Code {proc.returncode}: {(proc.stderr or '')[:300]}")
    return proc.stdout


def select_provider(tenant: Tenant, s: config.Settings | None = None) -> str:
    """Sovereign-Tenants bekommen nie bedrock-eu, auch wenn LLM_PROVIDER das sagt."""
    s = s or config.settings()
    if tenant.tier == config.TIER_SOVEREIGN:
        if s.llm_provider in NON_US_CHAIN:
            return s.llm_provider
        return "selfhost-eu" if s.selfhost_llm_base_url else "mistral-eu"
    return s.llm_provider or "bedrock-eu"


class LLM:
    """Strukturierte Aufrufe (Tool-Use bzw. JSON-Schema) über einen EU-Provider."""

    def __init__(
        self,
        tenant: Tenant,
        redis=None,
        cost_sink: Callable[[dict[str, Any]], None] | None = None,
        s: config.Settings | None = None,
        provider: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.2,
        tier: str | None = None,
        result_cache: Any = None,
        cache_scope: str = "",
        transport: Any = None,
        cli_runner: Callable[[Sequence[str], str], str] | None = None,
    ):
        self.s = s or config.settings()
        self.tenant, self.redis, self.cost_sink = tenant, redis, cost_sink
        self.provider = provider or select_provider(tenant, self.s)
        self.max_tokens, self.temperature = max_tokens, temperature
        self.tier = tier
        # Ergebnis-Cache je Quelle (``cache_scope``, z. B. Hash der Quelldatei), Stufe und Eingabe-Hash
        self.result_cache, self.cache_scope = result_cache, cache_scope
        # Nur für Tests: httpx-Transport und CLI-Aufruf austauschbar, damit kein Netz und kein Prozess nötig ist
        self._transport, self._cli_runner = transport, cli_runner
        assert_allowed(self.provider, tenant, self.s)
        if self.provider == CLAUDE_CLI_PROVIDER and self.s.app_env == "production":
            raise ResidencyError("claude-cli ist nur für Entwicklung erlaubt, nicht unter APP_ENV=production")

    def with_tier(self, tier: str, **overrides: Any) -> LLM:
        """Gleiche Verbindung, andere Modellstufe (Vorfilter, Editor, Richter, Eskalation)."""
        kw = dict(
            redis=self.redis, cost_sink=self.cost_sink, s=self.s, provider=self.provider, max_tokens=self.max_tokens,
            temperature=self.temperature, tier=tier, result_cache=self.result_cache, cache_scope=self.cache_scope,
            transport=self._transport, cli_runner=self._cli_runner,
        )  # fmt: skip
        kw.update(overrides)
        return LLM(self.tenant, **kw)

    # -- öffentlich ----------------------------------------------------------------------------
    def model(self) -> str:
        if self.provider in (ANTHROPIC_PROVIDER, CLAUDE_CLI_PROVIDER):
            return tier_model(self.provider, self.tier, self.s)
        if self.provider == "bedrock-eu":
            return self.s.bedrock_model_id
        if self.provider == "mistral-eu":
            return self.s.mistral_model
        if self.provider == "selfhost-eu":
            return self.s.selfhost_llm_model
        if self.provider == HEURISTIC_PROVIDER:
            return HEURISTIC_MODEL_ID
        return ""

    @property
    def is_heuristic(self) -> bool:
        """True für den Heuristik-Provider (Ergebnisse tragen ``heuristic_only``)."""
        return self.provider == HEURISTIC_PROVIDER

    def structured(
        self,
        system: str,
        user: str,
        schema: dict,
        tool_name: str,
        prompt_version: str,
        job_type: str = "llm_score",
        policy_block: str | None = None,
        cache_prefix: str | None = None,
        stage: str | None = None,
    ) -> dict:
        """Ein strukturierter Aufruf. ``policy_block`` und ``cache_prefix`` sind stabile Teile vor der Aufgabe
        (Richtlinie bzw. SOP, Transkript): bei ``anthropic`` eigene Cache-Blöcke, sonst vor den Nutzertext
        gesetzt. ``stage`` benennt die Stufe im Kostenbuch und im Ergebnis-Cache (Standard ``job_type``)."""
        model = self._require_model()
        stage = stage or job_type
        payload = [system, policy_block, cache_prefix, user, schema] if (policy_block or cache_prefix) else [system, user, schema]
        key = cache_key(self.provider, model, prompt_version, payload)
        if self.redis is not None:
            hit = self.redis.get(key)
            if hit:
                return json.loads(hit)
        # Ergebnis-Cache immer mit allen fünf Teilen, damit Einzel- und Batch-Aufrufe dieselben Keys treffen
        rkey = self._result_key(stage, model, prompt_version, [system, policy_block, cache_prefix, user, schema])
        if rkey is not None:
            hit = self.result_cache.get(rkey)
            if isinstance(hit, dict):
                self._sink(model, prompt_version, job_type, stage, {"cached_result": True, "billing": self._billing()})
                return hit
        out, usage = self._call_checked(system, user, schema, tool_name, model, policy_block, cache_prefix, prompt_version, job_type, stage)
        if self.redis is not None:
            self.redis.set(key, json.dumps(out, ensure_ascii=False), ex=CACHE_TTL_S)
        if rkey is not None:
            self.result_cache.put(rkey, out)
        self._sink(model, prompt_version, job_type, stage, usage)
        log.info(
            "llm provider=%s model=%s prompt=%s in=%s cached_in=%s out=%s",
            self.provider, model, prompt_version, usage.get("in"), usage.get("cached_in", 0), usage.get("out"),
        )  # fmt: skip
        return out

    def structured_many(
        self,
        items: Sequence[dict[str, Any]],
        batch: bool = False,
        poll_s: float = 30.0,
        timeout_s: float = 24 * 3600.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> list[dict | Exception]:
        """Viele unabhängige Aufrufe. ``items`` je ``{"id", "system", "user", "schema", "tool_name",
        "prompt_version", "job_type"?, "policy_block"?, "cache_prefix"?, "stage"?}``.

        Mit ``batch=True`` und Provider ``anthropic`` über Message Batches (halber Preis, Ergebnis innerhalb von
        24 h; für Eval- und Trainingsläufe, nie für den Nutzerpfad). Sonst nacheinander über ``structured``.
        Rückgabe in Eingabereihenfolge; ein fehlgeschlagener Eintrag ist die Ausnahme statt des Ergebnisses."""
        if not (batch and self.provider == ANTHROPIC_PROVIDER):
            results: list[dict | Exception] = []
            for it in items:
                try:
                    results.append(self.structured(
                        it["system"], it["user"], it["schema"], it["tool_name"], it["prompt_version"],
                        job_type=it.get("job_type", "llm_score"), policy_block=it.get("policy_block"),
                        cache_prefix=it.get("cache_prefix"), stage=it.get("stage"),
                    ))  # fmt: skip
                except Exception as exc:  # noqa: BLE001 - je Eintrag gemeldet, der Rest läuft weiter
                    results.append(exc)
            return results
        model = self._require_model()
        out: dict[int, dict | Exception] = {}
        pending: list[tuple[int, dict, str | None, list]] = []
        for n, it in enumerate(items):
            payload = [it["system"], it.get("policy_block"), it.get("cache_prefix"), it["user"], it["schema"]]
            rkey = self._result_key(it.get("stage") or it.get("job_type", "llm_score"), model, it["prompt_version"], payload)
            hit = self.result_cache.get(rkey) if rkey is not None else None
            if isinstance(hit, dict):
                out[n] = hit
                self._sink(model, it["prompt_version"], it.get("job_type", "llm_score"), it.get("stage"), {"cached_result": True, "billing": "batch"})
                continue
            pending.append((n, it, rkey, payload))
        if pending:
            client = AnthropicBatch(self.s, transport=self._transport)
            requests = [
                {"custom_id": f"r{n}", "params": anthropic_params(
                    it["system"], it["user"], it["schema"], it["tool_name"], model, self.max_tokens, self.temperature,
                    it.get("policy_block"), it.get("cache_prefix"),
                )}
                for n, it, _k, _p in pending
            ]  # fmt: skip
            batch_id = client.submit(requests)
            client.wait(batch_id, poll_s=poll_s, timeout_s=timeout_s, sleep=sleep)
            got = client.results(batch_id)
            for n, it, rkey, _p in pending:
                res = got.get(f"r{n}")
                if res is None or not res.get("ok"):
                    out[n] = RuntimeError(f"Batch-Eintrag r{n} ohne Ergebnis: {(res or {}).get('error') or 'fehlt'}")
                    continue
                try:
                    obj, usage = parse_anthropic_message(res["message"], it["tool_name"])
                    self._validate(obj, it["schema"])
                except SchemaError as exc:
                    out[n] = exc
                    continue
                if rkey is not None:
                    self.result_cache.put(rkey, obj)
                self._sink(model, it["prompt_version"], it.get("job_type", "llm_score"), it.get("stage"), {**usage, "billing": "batch"})
                out[n] = obj
        return [out[n] for n in range(len(items))]

    # -- intern --------------------------------------------------------------------------------
    def _require_model(self) -> str:
        model = self.model()
        if not model:
            raise RuntimeError(
                f"Kein Modell für Provider {self.provider} konfiguriert "
                "(BEDROCK_MODEL_ID, MISTRAL_MODEL oder SELFHOST_LLM_MODEL setzen)"
            )
        return model

    def _billing(self) -> str:
        if self.provider == CLAUDE_CLI_PROVIDER:
            return "dev_subscription"
        if self.provider == HEURISTIC_PROVIDER:
            return "local"
        return "api"

    def _result_key(self, stage: str, model: str, prompt_version: str, payload: Any) -> str | None:
        if self.result_cache is None:
            return None
        return self.result_cache.key(
            self.cache_scope or "global", stage, [self.provider, model, prompt_version, payload], "llm_v1"
        )

    def _sink(self, model: str, prompt_version: str, job_type: str, stage: str | None, usage: dict[str, Any]) -> None:
        if not self.cost_sink:
            return
        self.cost_sink({
            "tenant": self.tenant.id, "provider": self.provider, "model": model, "prompt": prompt_version,
            "job_type": job_type, "stage": stage or job_type, "tier": self.tier, "billing": self._billing(), **usage,
        })  # fmt: skip

    def _call_checked(self, system, user, schema, tool_name, model, policy_block, cache_prefix, prompt_version, job_type, stage):
        """Aufruf plus Schema-Prüfung. Bei ``claude-cli`` und ``anthropic`` gibt es nach einer unlesbaren Antwort
        genau einen Wiederholversuch mit Korrekturhinweis; der gescheiterte Versuch steht mit seinen Tokens im
        Kostenbuch (``schema_retry``). Scheitert auch der zweite, geht der ``SchemaError`` an den Aufrufer."""
        try:
            out, usage = self._call(system, user, schema, tool_name, model, policy_block, cache_prefix)
            try:
                self._validate(out, schema)
            except SchemaError as exc:
                raise SchemaError(str(exc), usage) from None
            return out, usage
        except SchemaError as exc:
            if self.provider not in SCHEMA_RETRY_PROVIDERS:
                raise
            first = exc
        self._sink(model, prompt_version, job_type, stage, {**first.usage, "schema_retry": True})
        hint = CORRECTION_HINT.format(error=str(first)[:200], required=", ".join(schema.get("required") or []) or "-")
        log.warning("llm provider=%s model=%s prompt=%s unlesbare Antwort, ein Wiederholversuch: %s", self.provider, model, prompt_version, first)
        out, usage = self._call(system, f"{user}\n\n{hint}", schema, tool_name, model, policy_block, cache_prefix)
        self._validate(out, schema)
        return out, {**usage, "schema_retry": True}

    def _call(self, system, user, schema, tool_name, model, policy_block, cache_prefix):
        if self.provider == ANTHROPIC_PROVIDER:
            return self._anthropic(system, user, schema, tool_name, model, policy_block, cache_prefix)
        if self.provider == CLAUDE_CLI_PROVIDER:
            return self._claude_cli(system, full_user_text(user, policy_block, cache_prefix), schema, tool_name, model)
        caller = {
            "bedrock-eu": self._bedrock,
            "mistral-eu": self._openai_compat,
            "selfhost-eu": self._openai_compat,
            HEURISTIC_PROVIDER: self._heuristic,
        }[self.provider]
        return caller(system, full_user_text(user, policy_block, cache_prefix), schema, tool_name, model)

    # -- Provider ------------------------------------------------------------------------------
    def _bedrock(self, system, user, schema, tool_name, model):
        host = f"bedrock-runtime.{self.s.aws_region}.amazonaws.com"
        residency.assert_eu_host(f"https://{host}", self.s)
        import boto3

        client = boto3.client("bedrock-runtime", region_name=self.s.aws_region, endpoint_url=f"https://{host}")
        r = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            toolConfig={
                "tools": [{"toolSpec": {"name": tool_name, "description": tool_name, "inputSchema": {"json": schema}}}],
                "toolChoice": {"tool": {"name": tool_name}},
            },
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
        )
        blocks = r.get("output", {}).get("message", {}).get("content", [])
        out = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
        if out is None:
            raise SchemaError("Kein Tool-Output vom Modell erhalten")
        u = r.get("usage", {})
        return out, {"in": u.get("inputTokens", 0), "out": u.get("outputTokens", 0)}

    def _openai_compat(self, system, user, schema, tool_name, model):
        """Mistral-EU und Selfhost (vLLM, TGI, Ollama) sprechen dasselbe Chat-Completions-Format."""
        if self.provider == "mistral-eu":
            base, api_key = self.s.mistral_base_url, self.s.mistral_api_key
        else:
            base, api_key = self.s.selfhost_llm_base_url, self.s.selfhost_llm_api_key
        if not base:
            raise RuntimeError(f"Basis-URL für Provider {self.provider} fehlt")
        url = base.rstrip("/") + "/v1/chat/completions"
        residency.assert_eu_host(url, self.s)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        body = {
            "model": model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": tool_name, "schema": schema, "strict": True},
            },
        }
        with residency.guarded_client(self.s, timeout=120) as client:
            r = client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        try:
            content = data["choices"][0]["message"]["content"]
            out = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise SchemaError(f"Antwort nicht als JSON lesbar: {exc}") from exc
        u = data.get("usage", {})
        return out, {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}

    def _anthropic(self, system, user, schema, tool_name, model, policy_block=None, cache_prefix=None):
        """Messages API mit erzwungenem Tool und Cache-Marken; der Host läuft durch den Residency-Guard."""
        body = anthropic_params(system, user, schema, tool_name, model, self.max_tokens, self.temperature, policy_block, cache_prefix)
        data = anthropic_request(self.s, "POST", "/v1/messages", body, transport=self._transport)
        return parse_anthropic_message(data, tool_name)

    def _claude_cli(self, system, user, schema, tool_name, model):
        """Nur Entwicklung: Prompt an ``claude -p``, Antwort als JSON. Kosten 0 € (``dev_subscription``)."""
        if self.s.app_env == "production":
            raise ResidencyError("claude-cli ist nur für Entwicklung erlaubt, nicht unter APP_ENV=production")
        prompt = (
            f"{system}\n\n{user}\n\n"
            f"Antworte ausschließlich mit einem JSON-Objekt für das Werkzeug {tool_name}, ohne Erklärung und ohne "
            f"Codeblock. Es muss diesem JSON-Schema entsprechen:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        argv = [self.s.claude_cli_bin or "claude", "-p", "--model", model, "--output-format", "json"]
        # Zusatzflags aus CHOPSTR_CLAUDE_CLI_ARGS: die CLI schickt ihren eigenen Systemprompt und ihre Werkzeuge mit,
        # deshalb sind ihre Tokens je Aufruf deutlich höher als über die API (siehe costlog, eur_api_equivalent).
        if self.s.claude_cli_args:
            import shlex

            argv += shlex.split(self.s.claude_cli_args)
        raw = (self._cli_runner or run_cli)(argv, prompt)
        return parse_cli_output(raw, schema.get("required") or ())

    def _heuristic(self, system, user, schema, tool_name, model):
        """Kein Netz, kein Residency-Hook nötig: die Antwort entsteht lokal aus dem gerenderten Prompt."""
        from . import heuristic_llm

        return heuristic_llm.answer(tool_name, user, schema), {"in": 0, "out": 0}

    # -- Validierung ---------------------------------------------------------------------------
    @staticmethod
    def _validate(out: Any, schema: dict) -> None:
        """Minimale Schema-Prüfung: Objekt, Pflichtfelder vorhanden. Tiefere Prüfung macht der Aufrufer."""
        if not isinstance(out, dict):
            raise SchemaError("Antwort ist kein Objekt")
        missing = [k for k in schema.get("required", []) if k not in out]
        if missing:
            raise SchemaError(f"Pflichtfelder fehlen: {missing}")


def anthropic_request(
    s: config.Settings, method: str, path: str, body: Any = None, transport: Any = None, raw: bool = False, url: str | None = None
) -> Any:
    """Ein Aufruf an die Anthropic-API über ``guarded_client``. Der Key steht nur im Header, nie im Log."""
    if not s.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY fehlt (Provider anthropic)")
    target = url or (s.anthropic_base_url.rstrip("/") + path)
    residency.assert_eu_host(target, s)
    headers = {"x-api-key": s.anthropic_api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
    extra = {"transport": transport} if transport is not None else {}
    with residency.guarded_client(s, timeout=300, **extra) as client:
        r = client.request(method, target, headers=headers, json=body) if body is not None else client.request(method, target, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f"Anthropic-API {method} {path or target} antwortet {r.status_code}: {r.text[:300]}")
    return r.text if raw else r.json()


class AnthropicBatch:
    """Message Batches: einreichen, pollen, Ergebnisse einsammeln (für Eval- und Trainingsläufe)."""

    def __init__(self, s: config.Settings | None = None, transport: Any = None):
        self.s = s or config.settings()
        self._transport = transport

    def submit(self, requests: list[dict[str, Any]]) -> str:
        data = anthropic_request(self.s, "POST", "/v1/messages/batches", {"requests": requests}, transport=self._transport)
        log.info("anthropic batch submitted id=%s n=%s", data.get("id"), len(requests))
        return str(data["id"])

    def status(self, batch_id: str) -> dict[str, Any]:
        return anthropic_request(self.s, "GET", f"/v1/messages/batches/{batch_id}", transport=self._transport)

    def wait(self, batch_id: str, poll_s: float = 30.0, timeout_s: float = 24 * 3600.0, sleep: Callable[[float], None] = time.sleep) -> dict:
        """Pollt, bis ``processing_status`` ``ended`` ist; nach ``timeout_s`` ``TimeoutError``."""
        waited = 0.0
        while True:
            st = self.status(batch_id)
            if st.get("processing_status") == "ended":
                return st
            if waited >= timeout_s:
                raise TimeoutError(f"Batch {batch_id} nach {int(waited)} s nicht fertig")
            sleep(poll_s)
            waited += poll_s

    def results(self, batch_id: str) -> dict[str, dict[str, Any]]:
        """JSONL der Ergebnisse je ``custom_id``: ``{"ok", "message"}`` oder ``{"ok": False, "error"}``."""
        st = self.status(batch_id)
        url = st.get("results_url")
        text = anthropic_request(
            self.s, "GET", f"/v1/messages/batches/{batch_id}/results", transport=self._transport, raw=True, url=url or None
        )
        out: dict[str, dict[str, Any]] = {}
        for line in str(text).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            res = row.get("result") or {}
            if res.get("type") == "succeeded":
                out[str(row.get("custom_id"))] = {"ok": True, "message": res.get("message") or {}}
            else:
                err = res.get("error") or {}
                out[str(row.get("custom_id"))] = {"ok": False, "error": f"{res.get('type')}: {err.get('type') or err}"}
        return out


# Zweiter Provider (Lane P3, Gegenleser): nur, wenn ``LLM_PROVIDER_SECOND`` gesetzt ist. Gelesen direkt aus der
# Umgebung des Worker-Prozesses, wie ``CHOPSTR_POLICY_VERSION``. Der Heuristik-Provider ist kein zweites Modell;
# ``critic.counter_read_model`` ruft ihn nie und markiert ihn so.
SECOND_PROVIDER_ENV = "LLM_PROVIDER_SECOND"


def second_llm(primary: Any) -> LLM | None:
    """Zweite Instanz für den Gegenleser oder ``None``, wenn ``LLM_PROVIDER_SECOND`` leer ist oder das erste
    Modell keinen Tenant trägt. Tenant, Redis und Kostenerfassung kommen vom ersten Modell; der Residency-Guard
    prüft den zweiten Provider wie jeden anderen (``assert_allowed`` im Konstruktor)."""
    import os

    provider = os.environ.get(SECOND_PROVIDER_ENV, "").strip()
    tenant = getattr(primary, "tenant", None)
    if not provider or not isinstance(tenant, Tenant):
        return None
    return LLM(
        tenant, redis=getattr(primary, "redis", None), cost_sink=getattr(primary, "cost_sink", None),
        s=getattr(primary, "s", None), provider=provider,
    )  # fmt: skip


__all__ = [
    "ANTHROPIC_PROVIDER",
    "CLAUDE_CLI_PROVIDER",
    "CLI_TIER_ALIASES",
    "DEFAULT_TIER_MODELS",
    "TIERS",
    "AnthropicBatch",
    "anthropic_params",
    "anthropic_request",
    "extract_json_object",
    "parse_cli_output",
    "parse_anthropic_message",
    "run_cli",
    "tier_model",
    "SECOND_PROVIDER_ENV",
    "second_llm",
    "EU_OK",
    "HEURISTIC_MODEL_ID",
    "HEURISTIC_PROVIDER",
    "LLM",
    "NON_US_CHAIN",
    "ResidencyError",
    "SchemaError",
    "Tenant",
    "assert_allowed",
    "cache_key",
    "select_provider",
]
