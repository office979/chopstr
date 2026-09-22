"""Client für die internen Endpunkte der Web-App (PHASE5.md, „Interne Schnittstelle Worker ↔ Web“).

Provider-SDKs und OAuth-Flows leben in der Web-App; der Worker besitzt Zeitplanung, Retries und
Metrik-Fenster und ruft deshalb ``/api/internal/publish``, ``/api/internal/metrics`` und
``/api/internal/mail`` auf. Auth über ``X-Internal-Secret`` (``INTERNAL_API_SECRET``), Host aus
``APP_INTERNAL_URL`` (steht auf der Allowlist des Residency-Guards). Der HTTP-Client kommt aus
``residency.guarded_client``; Tests tauschen ``client()`` gegen einen ``httpx.MockTransport`` aus.
"""

from __future__ import annotations

import logging
from typing import Any

from . import config, residency

log = logging.getLogger("chopstr.internal_api")

TIMEOUT_S = 60.0
METRIC_WINDOWS = ("6h", "48h", "7d")
METRIC_KEYS = ("views", "likes", "comments", "shares", "saves", "follows", "avg_watch_time_s", "retention_curve")


class InternalApiError(RuntimeError):
    """Die Web-App hat nicht mit 2xx oder nicht mit JSON geantwortet."""


def base_url(s: config.Settings | None = None) -> str:
    s = s or config.settings()
    url = (s.app_internal_url or "").strip().rstrip("/")
    if not url:
        raise RuntimeError("APP_INTERNAL_URL ist nicht gesetzt")
    return url


def client(s: config.Settings | None = None, **kwargs):
    """Geschützter ``httpx.Client`` mit Basis-URL und Secret-Header."""
    s = s or config.settings()
    if not s.internal_api_secret:
        raise RuntimeError("INTERNAL_API_SECRET ist nicht gesetzt")
    headers = {"X-Internal-Secret": s.internal_api_secret, "User-Agent": f"chopstr-worker/{s.app_version}"}
    kwargs.setdefault("timeout", TIMEOUT_S)
    return residency.guarded_client(s, base_url=base_url(s), headers=headers, **kwargs)


def post(path: str, body: dict[str, Any], s: config.Settings | None = None, http=None) -> dict[str, Any]:
    """POST an ``/api/internal/<path>``; Antwort als Dict. Nicht-2xx oder kein JSON: ``InternalApiError``."""
    s = s or config.settings()
    path = "/api/internal/" + path.strip("/")
    own = http is None
    http = http or client(s)
    try:
        r = http.post(path, json=body)
    finally:
        if own:
            http.close()
    if r.status_code // 100 != 2:
        detail = ""
        try:
            detail = str((r.json().get("error") or {}).get("message") or r.json().get("error") or "")
        except Exception:
            detail = r.text[:200]
        raise InternalApiError(f"{path} antwortete mit {r.status_code}: {detail}".rstrip(": "))
    try:
        data = r.json()
    except Exception as exc:
        raise InternalApiError(f"{path} lieferte kein JSON") from exc
    if not isinstance(data, dict):
        raise InternalApiError(f"{path} lieferte kein Objekt")
    return data


def publish(publication_id: str, s: config.Settings | None = None, http=None) -> dict[str, Any]:
    """``{ status: "published" | "failed", external_id, external_url, error }``."""
    data = post("publish", {"publication_id": publication_id}, s, http)
    status = str(data.get("status") or "failed")
    if status not in ("published", "failed"):
        raise InternalApiError(f"/api/internal/publish lieferte unbekannten Status {status!r}")
    return {
        "status": status,
        "external_id": data.get("external_id"),
        "external_url": data.get("external_url"),
        "error": data.get("error"),
    }


def metrics(publication_id: str, window: str, s: config.Settings | None = None, http=None) -> dict[str, Any]:
    """``metrics``-Objekt mit allen acht Schlüsseln; nicht garantierte Felder sind ``None``."""
    if window not in METRIC_WINDOWS:
        raise ValueError(f"Unbekanntes Metrik-Fenster {window!r}")
    data = post("metrics", {"publication_id": publication_id, "window": window}, s, http)
    raw = data.get("metrics")
    if not isinstance(raw, dict):
        raise InternalApiError("/api/internal/metrics lieferte kein metrics-Objekt")
    return {k: raw.get(k) for k in METRIC_KEYS}


def mail(to: list[str], subject: str, text: str, html: str | None = None, s: config.Settings | None = None, http=None) -> bool:
    """Versand über die Web-App. Gibt ``ok`` zurück."""
    recipients = [t for t in (to or []) if t]
    if not recipients:
        return False
    body: dict[str, Any] = {"to": recipients, "subject": subject, "text": text}
    if html:
        body["html"] = html
    data = post("mail", body, s, http)
    return bool(data.get("ok"))


__all__ = [
    "METRIC_KEYS",
    "METRIC_WINDOWS",
    "TIMEOUT_S",
    "InternalApiError",
    "base_url",
    "client",
    "mail",
    "metrics",
    "post",
    "publish",
]
