"""Webhook-Zustellung (Phase 5a): ``dispatch_outbox``, ``find_due_deliveries``, ``deliver_webhook``.

``dispatch_outbox(limit)`` liest unverarbeitete ``outbox_events`` und legt je aktivem Endpunkt mit passendem
Ereignis eine ``webhook_deliveries``-Zeile an (``pending``, sofort fällig), dann ``processed_at``.
``deliver_webhook(delivery_id)`` sendet den JSON-Body per POST mit ``X-Chopstr-Signature: t=<unix>,v1=<hex>``
(HMAC-SHA256 über ``"<t>.<body>"``), ``X-Chopstr-Event`` und ``X-Chopstr-Delivery``. Erfolg ist 2xx.
Fehlschläge: erster Versuch plus fünf Wiederholungen mit Backoff 1, 5, 30, 120, 720 Minuten über
``next_attempt_at``; danach ``failed``. Ein privater oder lokaler Ziel-Host (``residency.assert_webhook_host``)
und ein deaktivierter Endpunkt sind sofort ``failed`` (nicht wiederholbar). Payloads enthalten keine
Transkriptinhalte; Logs nur IDs, Zähler und Statuscodes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import activity

from .. import db, residency
from . import common

log = logging.getLogger("chopstr.activities.webhooks")

BACKOFF_MINUTES = (1, 5, 30, 120, 720)
MAX_ATTEMPTS = len(BACKOFF_MINUTES) + 1  # erster Versuch plus fünf Wiederholungen
DISPATCH_LIMIT = 200
SIGNATURE_VERSION = "v1"
SIGNATURE_TOLERANCE_S = 300

SQL_PENDING_OUTBOX = (
    "select id, workspace_id, event, entity, entity_id, payload, created_at from outbox_events "
    "where processed_at is null order by id limit %s"
)
SQL_ENDPOINTS = "select id, events from webhook_endpoints where workspace_id = %s and active"
SQL_DELIVERY = (
    "select d.id, d.endpoint_id, d.event, d.payload, d.attempt, d.status, d.created_at, "
    "e.url, e.secret, e.active, e.workspace_id "
    "from webhook_deliveries d join webhook_endpoints e on e.id = d.endpoint_id where d.id = %s"
)
SQL_DUE = (
    "select id from webhook_deliveries where status = 'pending' and next_attempt_at <= %s "
    "order by next_attempt_at limit %s"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return str(value)


# -- Signatur ------------------------------------------------------------------------------------
def sign(secret: str, body: bytes, ts: int | None = None) -> str:
    """``t=<unix>,v1=<hex(hmac_sha256(secret, "<t>.<body>"))>``."""
    ts = int(ts if ts is not None else time.time())
    mac = hmac.new(secret.encode("utf-8"), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},{SIGNATURE_VERSION}={mac}"


def verify(secret: str, body: bytes, header: str, now: int | None = None, tolerance_s: int = SIGNATURE_TOLERANCE_S) -> bool:
    """Prüfung auf Empfängerseite (Referenz für die Dokumentation und Tests)."""
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        return False
    now = int(now if now is not None else time.time())
    if abs(now - ts) > tolerance_s:
        return False
    expected = sign(secret, body, ts).split(f"{SIGNATURE_VERSION}=", 1)[1]
    return hmac.compare_digest(expected, parts.get(SIGNATURE_VERSION, ""))


def build_body(delivery: dict[str, Any]) -> bytes:
    """Stabiler JSON-Body (gleich für alle Versuche): ID, Ereignis, Zeitstempel, Daten."""
    doc = {
        "id": str(delivery["id"]),
        "event": delivery["event"],
        "created_at": _iso(delivery.get("created_at")),
        "data": dict(delivery.get("payload") or {}),
    }
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


# -- Dispatch ------------------------------------------------------------------------------------
def run_dispatch_outbox(ctx: common.Context, limit: int = DISPATCH_LIMIT) -> dict[str, int]:
    """Unverarbeitete Outbox-Ereignisse in ``webhook_deliveries`` verteilen und als verarbeitet markieren."""
    events = db.fetch_all(ctx.conn, SQL_PENDING_OUTBOX, (int(limit),))
    deliveries = 0
    endpoints_cache: dict[str, list[tuple[str, list[str]]]] = {}
    for oid, workspace_id, event, _entity, _entity_id, payload, _created in events:
        ws = str(workspace_id)
        if ws not in endpoints_cache:
            endpoints_cache[ws] = [(str(eid), list(evs or [])) for eid, evs in db.fetch_all(ctx.conn, SQL_ENDPOINTS, (ws,))]
        for endpoint_id, subscribed in endpoints_cache[ws]:
            if event not in subscribed and "*" not in subscribed:
                continue
            db.insert(
                ctx.conn,
                "webhook_deliveries",
                endpoint_id=endpoint_id,
                outbox_id=oid,
                event=event,
                payload=db.jsonb(_json(payload, {}) or {}),
                attempt=0,
                status="pending",
                next_attempt_at=_now(),
            )
            deliveries += 1
        db.update(ctx.conn, "outbox_events", {"id": oid}, processed_at=_now())
    log.info("outbox dispatch events=%s deliveries=%s", len(events), deliveries)
    return {"events": len(events), "deliveries": deliveries}


def run_find_due_deliveries(ctx: common.Context, now: datetime | None = None, limit: int = DISPATCH_LIMIT) -> list[str]:
    now = now or _now()
    return [str(r[0]) for r in db.fetch_all(ctx.conn, SQL_DUE, (now, int(limit)))]


# -- Zustellung ----------------------------------------------------------------------------------
def load_delivery(ctx: common.Context, delivery_id: str) -> dict[str, Any]:
    row = db.fetch_one(ctx.conn, SQL_DELIVERY, (delivery_id,))
    if row is None:
        raise LookupError(f"Zustellung {delivery_id} nicht gefunden")
    keys = ["id", "endpoint_id", "event", "payload", "attempt", "status", "created_at", "url", "secret", "active", "workspace_id"]
    out = dict(zip(keys, row))
    out["id"] = str(out["id"])
    out["payload"] = _json(out.get("payload"), {}) or {}
    out["attempt"] = int(out.get("attempt") or 0)
    return out


def _finish(ctx: common.Context, delivery_id: str, **values: Any) -> dict[str, Any]:
    db.update(ctx.conn, "webhook_deliveries", {"id": delivery_id}, **values)
    out = {"delivery_id": delivery_id, **values}
    if isinstance(out.get("next_attempt_at"), datetime):
        out["next_attempt_at"] = out["next_attempt_at"].isoformat()
    if isinstance(out.get("delivered_at"), datetime):
        out["delivered_at"] = out["delivered_at"].isoformat()
    return out


def run_deliver_webhook(ctx: common.Context, delivery_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Ein Zustellversuch. Ergebnis ``{status, attempt, response_code, error, next_attempt_at?}``."""
    now = now or _now()
    d = load_delivery(ctx, delivery_id)
    if d["status"] != "pending":
        return {"delivery_id": delivery_id, "status": d["status"], "attempt": d["attempt"], "skipped": True}
    if not d.get("active"):
        return _finish(ctx, delivery_id, status="failed", error="Endpunkt deaktiviert", attempt=d["attempt"])
    s = ctx.settings
    try:
        residency.assert_webhook_host(str(d["url"]), s)
    except residency.ResidencyError as exc:
        log.warning("webhook blocked delivery=%s error=%s", delivery_id, exc.__class__.__name__)
        return _finish(ctx, delivery_id, status="failed", error=str(exc)[:400], attempt=d["attempt"])

    attempt = d["attempt"] + 1
    body = build_body(d)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": f"chopstr-webhooks/{s.app_version}",
        "X-Chopstr-Event": str(d["event"]),
        "X-Chopstr-Delivery": delivery_id,
        "X-Chopstr-Attempt": str(attempt),
        "X-Chopstr-Signature": sign(str(d["secret"]), body, int(now.timestamp())),
    }
    code: int | None = None
    error: str | None = None
    try:
        with residency.webhook_client(s, timeout=max(1.0, s.webhook_timeout_ms / 1000.0)) as http:
            r = http.post(str(d["url"]), content=body, headers=headers)
        code = int(r.status_code)
        ok = 200 <= code < 300
        if not ok:
            error = f"HTTP {code}"
    except residency.ResidencyError as exc:
        return _finish(ctx, delivery_id, status="failed", error=str(exc)[:400], attempt=attempt)
    except Exception as exc:  # Netz, Timeout, TLS
        ok = False
        error = f"{exc.__class__.__name__}: {str(exc)[:200]}".rstrip(": ")

    if ok:
        log.info("webhook delivered delivery=%s attempt=%s code=%s", delivery_id, attempt, code)
        return _finish(ctx, delivery_id, status="delivered", attempt=attempt, response_code=code, error=None, delivered_at=now)
    if attempt >= MAX_ATTEMPTS:
        log.warning("webhook failed delivery=%s attempt=%s code=%s", delivery_id, attempt, code)
        return _finish(ctx, delivery_id, status="failed", attempt=attempt, response_code=code, error=error)
    wait = timedelta(minutes=BACKOFF_MINUTES[attempt - 1])
    log.info("webhook retry delivery=%s attempt=%s code=%s next_in=%s", delivery_id, attempt, code, wait)
    return _finish(
        ctx, delivery_id, status="pending", attempt=attempt, response_code=code, error=error, next_attempt_at=now + wait
    )


def _parse_now(value: str | datetime | None) -> datetime:
    if value is None:
        return _now()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@activity.defn(name="dispatch_outbox")
def dispatch_outbox(limit: int = DISPATCH_LIMIT) -> dict:
    ctx = common.open_context()
    try:
        return run_dispatch_outbox(ctx, limit)
    finally:
        ctx.close()


@activity.defn(name="find_due_deliveries")
def find_due_deliveries(now: str | None = None, limit: int = DISPATCH_LIMIT) -> list[str]:
    ctx = common.open_context()
    try:
        return run_find_due_deliveries(ctx, _parse_now(now), limit)
    finally:
        ctx.close()


@activity.defn(name="deliver_webhook")
def deliver_webhook(delivery_id: str) -> dict:
    ctx = common.open_context()
    try:
        return run_deliver_webhook(ctx, delivery_id)
    finally:
        ctx.close()


__all__ = [
    "BACKOFF_MINUTES",
    "DISPATCH_LIMIT",
    "MAX_ATTEMPTS",
    "build_body",
    "deliver_webhook",
    "dispatch_outbox",
    "find_due_deliveries",
    "load_delivery",
    "run_deliver_webhook",
    "run_dispatch_outbox",
    "run_find_due_deliveries",
    "sign",
    "verify",
]
