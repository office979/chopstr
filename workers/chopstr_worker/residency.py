"""Residency-Guard: kein Byte verlässt die EU.

Zwei Ebenen:

1. **Provider-Allowlist** (aus dem Gerüst): ``EU_OK`` sind Anbieter mit EU-Verarbeitung,
   ``NON_US_CHAIN`` die Teilmenge ohne US-Anbieter in der Kette (für Sovereign-Tenants).
2. **Host-Allowlist** für ausgehende HTTP-Aufrufe: ``assert_eu_host(url)`` wirft
   ``ResidencyError`` für jeden Host, der nicht aus der Konfiguration (S3, LanguageTool,
   Temporal, Bedrock-EU, Mistral, Selfhost, Gladia) oder ``EGRESS_ALLOWLIST`` stammt.
   ``guarded_client()`` liefert einen ``httpx.Client`` mit Request-Hook, der jede Anfrage
   an einen nicht erlaubten Host abbricht, bevor sie das Netz erreicht.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import config

EU_OK = {"bedrock-eu", "mistral-eu", "selfhost-eu", "gladia-eu"}
NON_US_CHAIN = {"mistral-eu", "selfhost-eu", "gladia-eu"}  # für Sovereign-Tenants

# Immer erlaubt: lokale Entwicklung
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}

# Muster für EU-Regionen von AWS Bedrock (Runtime-Endpunkte)
_BEDROCK_EU = re.compile(r"^bedrock(-runtime)?\.eu-[a-z]+-\d+\.amazonaws\.com$")

# Bekannte Nicht-EU-Endpunkte: immer gesperrt, auch wenn sie versehentlich in der Konfiguration stehen
DENY_PATTERNS = (
    re.compile(r"(^|\.)openai\.com$"),
    re.compile(r"(^|\.)anthropic\.com$"),
    re.compile(r"(^|\.)googleapis\.com$"),
    re.compile(r"(^|\.)openai\.azure\.com$"),
    re.compile(r"(^|\.)(us|ap|sa|ca|af|me|il|cn)-[a-z]+-\d+\.amazonaws\.com$"),
)


class ResidencyError(RuntimeError):
    """Ein Aufruf würde Daten außerhalb der EU verarbeiten. Nicht wiederholbar (non-retryable)."""


@dataclass
class Tenant:
    """Mandantenkontext für die Provider-Prüfung (Spiegel von ``workspaces.tier``)."""

    id: str
    tier: str = config.TIER_STANDARD
    allow_us_subprocessors: bool = False


def assert_allowed(provider: str, tenant: Tenant) -> None:
    """Provider-Prüfung: EU-Verarbeitung immer, Sovereign zusätzlich ohne US-Anbieter."""
    if provider not in EU_OK:
        raise ResidencyError(f"Anbieter {provider} verarbeitet nicht in der EU")
    if tenant.tier == config.TIER_SOVEREIGN and provider not in NON_US_CHAIN:
        raise ResidencyError(f"Anbieter {provider} ist für Sovereign-Workspace {tenant.id} nicht erlaubt")


def _host_of(value: str) -> str:
    """Host aus URL oder 'host:port'. Leerer String, wenn nichts Sinnvolles drinsteht."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "//" + value
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        return ""
    return host.lower().rstrip(".")


def allowed_hosts(s: config.Settings | None = None) -> set[str]:
    """Konfigurierte Hosts, an die der Worker sprechen darf."""
    s = s or config.settings()
    hosts = set(LOCAL_HOSTS)
    for value in (
        s.s3_endpoint,
        s.languagetool_url,
        s.temporal_address,
        s.mistral_base_url,
        s.selfhost_llm_base_url,
        s.gladia_base_url,
    ):
        h = _host_of(value)
        if h:
            hosts.add(h)
    hosts.add("api.mistral.ai")
    hosts.add(f"bedrock-runtime.{s.aws_region}.amazonaws.com")
    for entry in s.egress_allowlist:
        h = _host_of(entry)
        if h:
            hosts.add(h)
    return hosts


def host_denied(host: str) -> bool:
    """Bekannte Nicht-EU-Hosts (Deny-Liste hat Vorrang vor jeder Allowlist)."""
    return any(p.search(host) for p in DENY_PATTERNS)


def host_allowed(host: str, s: config.Settings | None = None) -> bool:
    host = (host or "").lower().rstrip(".")
    if not host or host_denied(host):
        return False
    if host in allowed_hosts(s):
        return True
    return bool(_BEDROCK_EU.match(host))


def assert_eu_host(url: str, s: config.Settings | None = None) -> str:
    """Wirft ``ResidencyError``, wenn der Host der URL nicht auf der Allowlist steht. Gibt den Host zurück."""
    host = _host_of(url)
    if not host:
        raise ResidencyError(f"Ziel-URL ohne gültigen Host: {url!r}")
    if host_denied(host):
        raise ResidencyError(f"Ausgehender Aufruf an {host} ist gesperrt (bekannter Nicht-EU-Endpunkt)")
    if not host_allowed(host, s):
        raise ResidencyError(
            f"Ausgehender Aufruf an {host} ist nicht erlaubt (nicht auf der EU-Allowlist). "
            "Host bei Bedarf über EGRESS_ALLOWLIST freigeben."
        )
    return host


def _make_hook(s: config.Settings | None):
    def _hook(request):
        assert_eu_host(str(request.url), s)

    return _hook


def guarded_client(s: config.Settings | None = None, **kwargs):
    """``httpx.Client`` mit Request-Hook: jede Anfrage an einen nicht erlaubten Host bricht mit
    ``ResidencyError`` ab, bevor eine Verbindung aufgebaut wird."""
    import httpx

    hooks = kwargs.pop("event_hooks", {}) or {}
    hooks.setdefault("request", [])
    hooks["request"] = [_make_hook(s), *hooks["request"]]
    return httpx.Client(event_hooks=hooks, **kwargs)


def guarded_async_client(s: config.Settings | None = None, **kwargs):
    """Asynchrones Gegenstück zu ``guarded_client``."""
    import httpx

    hook = _make_hook(s)

    async def _async_hook(request):
        hook(request)

    hooks = kwargs.pop("event_hooks", {}) or {}
    hooks.setdefault("request", [])
    hooks["request"] = [_async_hook, *hooks["request"]]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)


__all__ = [
    "DENY_PATTERNS",
    "EU_OK",
    "NON_US_CHAIN",
    "ResidencyError",
    "Tenant",
    "allowed_hosts",
    "assert_allowed",
    "assert_eu_host",
    "guarded_async_client",
    "guarded_client",
    "host_allowed",
    "host_denied",
]
