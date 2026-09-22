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
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from . import config, residency
from .residency import EU_OK, NON_US_CHAIN, ResidencyError, Tenant, assert_allowed

log = logging.getLogger("chopstr.llm")

CACHE_TTL_S = 60 * 60 * 24 * 30
HEURISTIC_PROVIDER = "local-heuristic"
HEURISTIC_MODEL_ID = "heuristic-v1"


class SchemaError(RuntimeError):
    """Antwort entspricht nicht dem Tool-Schema (non-retryable)."""


def cache_key(provider: str, model: str, prompt_version: str, payload: Any) -> str:
    raw = json.dumps([provider, model, prompt_version, payload], sort_keys=True, ensure_ascii=False)
    return "llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    ):
        self.s = s or config.settings()
        self.tenant, self.redis, self.cost_sink = tenant, redis, cost_sink
        self.provider = provider or select_provider(tenant, self.s)
        self.max_tokens, self.temperature = max_tokens, temperature
        assert_allowed(self.provider, tenant)

    # -- öffentlich ----------------------------------------------------------------------------
    def model(self) -> str:
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
    ) -> dict:
        model = self.model()
        if not model:
            raise RuntimeError(
                f"Kein Modell für Provider {self.provider} konfiguriert "
                "(BEDROCK_MODEL_ID, MISTRAL_MODEL oder SELFHOST_LLM_MODEL setzen)"
            )
        key = cache_key(self.provider, model, prompt_version, [system, user, schema])
        if self.redis is not None:
            hit = self.redis.get(key)
            if hit:
                return json.loads(hit)
        caller = {
            "bedrock-eu": self._bedrock,
            "mistral-eu": self._openai_compat,
            "selfhost-eu": self._openai_compat,
            HEURISTIC_PROVIDER: self._heuristic,
        }[self.provider]
        out, usage = caller(system, user, schema, tool_name, model)
        self._validate(out, schema)
        if self.redis is not None:
            self.redis.set(key, json.dumps(out, ensure_ascii=False), ex=CACHE_TTL_S)
        if self.cost_sink:
            self.cost_sink(
                {
                    "tenant": self.tenant.id,
                    "provider": self.provider,
                    "model": model,
                    "prompt": prompt_version,
                    "job_type": job_type,
                    **usage,
                }
            )
        log.info("llm provider=%s prompt=%s in=%s out=%s", self.provider, prompt_version, usage.get("in"), usage.get("out"))
        return out

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


__all__ = [
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
