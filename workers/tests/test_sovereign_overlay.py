"""Sovereign-Overlay (Phase 5c): keine US-Hosts in ``infra/docker-compose.sovereign.yml``, alle Hosts des
Overlays sind unter Sovereign-Settings vom Residency-Guard erlaubt, Provider ohne US-Kette."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from chopstr_worker import config, residency
from chopstr_worker.residency import Tenant

OVERLAY = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.sovereign.yml"
FORBIDDEN = ("amazonaws.com", "openai.com", "anthropic.com", "googleapis.com", "stripe.com")
_VAR = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*)|:\?[^}]*)?\}")


def resolve(value: str, env: dict[str, str] | None = None) -> str:
    """``${VAR:-default}`` mit ``env`` oder dem Default auflösen; ``${VAR:?msg}`` wird leer."""
    env = env or {}

    def sub(m: re.Match) -> str:
        return env.get(m.group(1), m.group(2) or "")

    return _VAR.sub(sub, value)


def env_of(service: dict) -> dict[str, str]:
    raw = service.get("environment") or {}
    if isinstance(raw, list):
        raw = dict(item.split("=", 1) if "=" in item else (item, "") for item in raw)
    return {str(k): resolve(str(v if v is not None else "")) for k, v in raw.items()}


def hosts_in(values: list[str], schemes: tuple[str, ...] = ("http", "https")) -> set[str]:
    """Hostnamen aller URL-artigen Werte (ohne Nutzerdaten und Port). Der Residency-Guard bewacht HTTP-Egress;
    ``postgres://`` und ``redis://`` sind stack-interne Verbindungen ohne HTTP-Client."""
    out = set()
    for v in values:
        for m in re.finditer(r"[a-z][a-z0-9+.-]*://[^\s'\"]+", v):
            parts = urlsplit(m.group(0))
            if parts.scheme in schemes and parts.hostname:
                out.add(parts.hostname.lower())
    return out


def test_overlay_has_no_us_hosts_anywhere():
    text = OVERLAY.read_text(encoding="utf-8").lower()
    for bad in FORBIDDEN:
        assert bad not in text, f"{bad} im Sovereign-Overlay"
    doc = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    assert set(doc["services"]) >= {"worker", "worker-gpu", "vllm", "web"}
    for name, svc in doc["services"].items():
        for k, v in env_of(svc).items():
            assert not any(bad in v.lower() for bad in FORBIDDEN), f"{name}.{k} = {v}"


def test_worker_env_selects_eu_chain_without_bedrock_and_no_hardcoded_model():
    doc = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    for name in ("worker", "worker-gpu"):
        env = env_of(doc["services"][name])
        assert env["LLM_PROVIDER"] in residency.NON_US_CHAIN and env["LLM_PROVIDER"] == "selfhost-eu"
        residency.assert_allowed(env["LLM_PROVIDER"], Tenant(id="ws-sov", tier=config.TIER_SOVEREIGN))
        assert env["BEDROCK_MODEL_ID"] == "" and env["SELFHOST_LLM_BASE_URL"] == "http://vllm:8000/v1"
        assert env["SELFHOST_LLM_MODEL"] == "" and env["GLADIA_BASE_URL"] == ""  # nur aus der Umgebung
    raw_worker = doc["services"]["worker"]["environment"]
    assert "${SELFHOST_LLM_MODEL" in str(raw_worker["SELFHOST_LLM_MODEL"])
    assert "${GLADIA_BASE_URL" in str(raw_worker["GLADIA_BASE_URL"])
    vllm = doc["services"]["vllm"]
    assert vllm["image"].startswith("vllm/vllm-openai")
    cmd = [str(c) for c in vllm["command"]]
    assert cmd[cmd.index("--model") + 1].startswith("${SELFHOST_LLM_MODEL")
    assert vllm["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]
    assert doc["services"]["worker-gpu"]["deploy"]["resources"]["reservations"]["devices"][0]["driver"] == "nvidia"
    web = env_of(doc["services"]["web"])
    assert web["BILLING_PROVIDER"] == "manual" and web["DEFAULT_TIER"] == "sovereign"


def test_all_overlay_hosts_pass_residency_guard_under_sovereign_settings(monkeypatch):
    doc = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    worker_env = env_of(doc["services"]["worker"])
    for key in ("LLM_PROVIDER", "SELFHOST_LLM_BASE_URL", "GLADIA_BASE_URL", "BEDROCK_MODEL_ID", "EGRESS_ALLOWLIST"):
        monkeypatch.setenv(key, worker_env.get(key, ""))
    monkeypatch.setenv("S3_ENDPOINT", "http://minio:9000")
    monkeypatch.setenv("LANGUAGETOOL_URL", "http://languagetool:8010/v2")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "temporal:7233")
    s = config.reload()
    values: list[str] = []
    for svc in doc["services"].values():
        values += list(env_of(svc).values())
        values += [resolve(str(c)) for c in (svc.get("command") or []) if not isinstance(svc.get("command"), str)]
    hosts = hosts_in(values) - {"localhost", "web"}  # web ist die interne API (APP_INTERNAL_URL, Allowlist der Web-Seite)
    assert "vllm" in hosts and "minio" in hosts
    for host in hosts:
        assert not residency.host_denied(host), host
        assert residency.host_allowed(host, s), f"{host} nicht auf der Sovereign-Allowlist"
    # Datenbank und Redis: Compose-Servicenamen, nie auf der Deny-Liste
    for host in hosts_in(values, ("postgres", "redis")):
        assert host in {"postgres", "redis"} and not residency.host_denied(host), host
    assert not residency.host_allowed("bedrock-runtime.us-east-1.amazonaws.com", s)
    assert residency.host_allowed("bedrock-runtime.eu-central-1.amazonaws.com", s)  # Host-Ebene; die Provider-Ebene
    # sperrt Bedrock für Sovereign-Tenants (test_residency.py), das Overlay setzt zusätzlich keine Bedrock-Modell-ID
    assert s.llm_provider == "selfhost-eu" and s.bedrock_model_id == ""
