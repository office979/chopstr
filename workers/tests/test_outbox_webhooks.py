"""Outbox (Hooks aus events.py), Webhook-Signatur, Dispatch, Zustellung mit Backoff, private Hosts gesperrt."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from chopstr_worker import config, events, outbox, residency
from chopstr_worker.activities import webhooks

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def ws_source(fake_db):
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/in.mp4", title="Interview")
    return wid, sid


# -- Outbox und Hooks ----------------------------------------------------------------------------
def test_source_status_hook_emits_ready_and_failed(fake_db, ws_source):
    wid, sid = ws_source
    events.set_source_status(fake_db, sid, "scoring")
    assert fake_db.outbox_events == []
    events.set_source_status(fake_db, sid, "ready")
    events.set_source_status(fake_db, sid, "failed", "Kandidatensuche fehlgeschlagen: x")
    assert [e["event"] for e in fake_db.outbox_events] == ["source.ready", "source.failed"]
    ready, failed = fake_db.outbox_events
    assert ready["workspace_id"] == wid and ready["entity"] == "source" and ready["entity_id"] == sid
    assert ready["payload"] == {"source_id": sid, "status": "ready", "title": "Interview"}
    assert failed["payload"]["error"].startswith("Kandidatensuche fehlgeschlagen")
    assert ready["processed_at"] is None


def test_unknown_source_and_unknown_event(fake_db):
    events.set_source_status(fake_db, "gibt-es-nicht", "ready")  # kein Absturz, keine Zeile
    assert fake_db.outbox_events == []
    with pytest.raises(ValueError):
        outbox.emit(fake_db, "ws", "source.exploded", "source", "x", {})


def test_render_step_hooks_emit_clip_rendered_and_failed(fake_db, ws_source):
    wid, sid = ws_source
    segs = [{"start": 0.0, "end": 20.0, "role": "body"}]
    cand = fake_db.add_candidate(sid, segs)
    cid = fake_db.add_clip(sid, cand, "linkedin", segs, duration_s=20.0)
    with events.step(fake_db, sid, "render", "Render gestartet", fail_status=None) as st:
        st.progress(0.05, "Copy", clip_id=cid, phase="copy")
        st.finish("fertig", clip_id=cid, file_key="renders/x.mp4")
    with pytest.raises(RuntimeError), events.step(fake_db, sid, "render", fail_status=None) as st:
        st.progress(0.05, "Copy", clip_id=cid, phase="copy")
        raise RuntimeError("ffmpeg fehlt")
    evs = [e["event"] for e in fake_db.outbox_events]
    assert evs == ["clip.rendered", "clip.failed"]
    rendered, failed = fake_db.outbox_events
    assert rendered["payload"] == {"clip_id": cid, "source_id": sid, "platform": "linkedin", "status": "rendered", "title": "Interview", "duration_s": 20.0}
    assert failed["payload"]["error"].startswith("Rendern fehlgeschlagen: ffmpeg fehlt")
    assert fake_db.sources[sid]["status"] == "uploaded"  # fail_status=None: Quellstatus bleibt


def test_other_steps_do_not_emit_clip_events(fake_db, ws_source):
    _wid, sid = ws_source
    with events.step(fake_db, sid, "heatmap", fail_status=None) as st:
        st.finish("ok", clip_id="irrelevant")
    assert fake_db.outbox_events == []


# -- Signatur ------------------------------------------------------------------------------------
def test_signature_roundtrip_and_tamper():
    body = b'{"event":"clip.rendered","id":"d1"}'
    header = webhooks.sign("whsec_abc", body, 1_800_000_000)
    assert header.startswith("t=1800000000,v1=") and len(header.split("v1=")[1]) == 64
    assert webhooks.verify("whsec_abc", body, header, now=1_800_000_100)
    assert not webhooks.verify("whsec_abc", body + b" ", header, now=1_800_000_100)
    assert not webhooks.verify("whsec_other", body, header, now=1_800_000_100)
    assert not webhooks.verify("whsec_abc", body, header, now=1_800_000_000 + 3600)  # zu alt
    assert not webhooks.verify("whsec_abc", body, "kaputt", now=1_800_000_000)


# -- Dispatch ------------------------------------------------------------------------------------
def test_dispatch_creates_one_delivery_per_matching_active_endpoint(fake_db, fake_context, ws_source):
    wid, sid = ws_source
    other = fake_db.add_workspace()
    hit = fake_db.add_webhook_endpoint(wid, "https://hooks.example.com/a", ["source.ready", "clip.rendered"])
    fake_db.add_webhook_endpoint(wid, "https://hooks.example.com/b", ["clip.failed"])
    fake_db.add_webhook_endpoint(wid, "https://hooks.example.com/c", ["source.ready"], active=False)
    fake_db.add_webhook_endpoint(other, "https://hooks.example.com/d", ["source.ready"])
    wildcard = fake_db.add_webhook_endpoint(wid, "https://hooks.example.com/e", ["*"])
    events.set_source_status(fake_db, sid, "ready")
    out = webhooks.run_dispatch_outbox(fake_context, limit=50)
    assert out == {"events": 1, "deliveries": 2}
    endpoints = sorted(d["endpoint_id"] for d in fake_db.webhook_deliveries.values())
    assert endpoints == sorted([hit, wildcard])
    d = next(iter(fake_db.webhook_deliveries.values()))
    assert d["status"] == "pending" and d["attempt"] == 0 and d["event"] == "source.ready" and d["payload"]["source_id"] == sid
    assert fake_db.outbox_events[0]["processed_at"] is not None
    assert webhooks.run_dispatch_outbox(fake_context) == {"events": 0, "deliveries": 0}
    due = webhooks.run_find_due_deliveries(fake_context, datetime.now(UTC) + timedelta(seconds=1))
    assert sorted(due) == sorted(fake_db.webhook_deliveries)


# -- Zustellung ----------------------------------------------------------------------------------
def _mock_client(monkeypatch, handler):
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(residency, "webhook_client", lambda s=None, **kw: httpx.Client(transport=httpx.MockTransport(_handler)))
    return seen


def _delivery(fake_db, wid, url="https://hooks.example.com/in", **endpoint_fields) -> str:
    eid = fake_db.add_webhook_endpoint(wid, url, ["clip.rendered"], secret="whsec_k", **endpoint_fields)
    did = "d-" + eid[:8]
    fake_db.webhook_deliveries[did] = {
        "id": did, "endpoint_id": eid, "outbox_id": 1, "event": "clip.rendered", "payload": {"clip_id": "c1", "status": "rendered"},
        "attempt": 0, "status": "pending", "response_code": None, "error": None, "next_attempt_at": NOW, "delivered_at": None, "created_at": NOW,
    }  # fmt: skip
    return did


def test_deliver_success_signs_body_and_sets_delivered(fake_db, fake_context, ws_source, monkeypatch):
    wid, _sid = ws_source
    seen = _mock_client(monkeypatch, lambda r: httpx.Response(204))
    did = _delivery(fake_db, wid)
    out = webhooks.run_deliver_webhook(fake_context, did, now=NOW)
    assert out["status"] == "delivered" and out["attempt"] == 1 and out["response_code"] == 204
    req = seen[0]
    assert req.method == "POST" and str(req.url) == "https://hooks.example.com/in"
    assert req.headers["X-Chopstr-Event"] == "clip.rendered" and req.headers["X-Chopstr-Delivery"] == did
    assert req.headers["Content-Type"].startswith("application/json")
    assert webhooks.verify("whsec_k", req.content, req.headers["X-Chopstr-Signature"], now=int(NOW.timestamp()))
    body = req.content.decode("utf-8")
    assert '"event":"clip.rendered"' in body and '"data":{"clip_id":"c1","status":"rendered"}' in body
    row = fake_db.webhook_deliveries[did]
    assert row["status"] == "delivered" and row["delivered_at"] == NOW and row["error"] is None
    # zweiter Aufruf: nichts mehr zu tun
    assert webhooks.run_deliver_webhook(fake_context, did, now=NOW)["skipped"] is True


def test_backoff_sequence_then_failed(fake_db, fake_context, ws_source, monkeypatch):
    wid, _sid = ws_source
    seen = _mock_client(monkeypatch, lambda r: httpx.Response(503, text="busy"))
    did = _delivery(fake_db, wid)
    waits = []
    now = NOW
    for attempt in range(1, webhooks.MAX_ATTEMPTS):
        out = webhooks.run_deliver_webhook(fake_context, did, now=now)
        assert out["status"] == "pending" and out["attempt"] == attempt and out["response_code"] == 503 and out["error"] == "HTTP 503"
        nxt = fake_db.webhook_deliveries[did]["next_attempt_at"]
        waits.append(int((nxt - now).total_seconds() // 60))
        assert webhooks.run_find_due_deliveries(fake_context, now) == []  # noch nicht fällig
        assert webhooks.run_find_due_deliveries(fake_context, nxt) == [did]
        now = nxt
    assert waits == list(webhooks.BACKOFF_MINUTES) == [1, 5, 30, 120, 720]
    out = webhooks.run_deliver_webhook(fake_context, did, now=now)
    assert out["status"] == "failed" and out["attempt"] == webhooks.MAX_ATTEMPTS == 6
    assert fake_db.webhook_deliveries[did]["status"] == "failed"
    assert len(seen) == 6
    assert int(seen[-1].headers["X-Chopstr-Attempt"]) == 6


def test_network_error_schedules_retry(fake_db, fake_context, ws_source, monkeypatch):
    wid, _sid = ws_source

    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    _mock_client(monkeypatch, boom)
    did = _delivery(fake_db, wid)
    out = webhooks.run_deliver_webhook(fake_context, did, now=NOW)
    assert out["status"] == "pending" and out["attempt"] == 1 and out["response_code"] is None
    assert out["error"].startswith("ConnectError")
    assert fake_db.webhook_deliveries[did]["next_attempt_at"] == NOW + timedelta(minutes=1)


def test_inactive_endpoint_fails_without_request(fake_db, fake_context, ws_source, monkeypatch):
    wid, _sid = ws_source
    seen = _mock_client(monkeypatch, lambda r: httpx.Response(200))
    did = _delivery(fake_db, wid, active=False)
    out = webhooks.run_deliver_webhook(fake_context, did, now=NOW)
    assert out["status"] == "failed" and out["error"] == "Endpunkt deaktiviert" and seen == []


@pytest.mark.parametrize("url", ["https://10.0.0.5/hook", "https://localhost/hook", "https://intern.local/hook", "http://hooks.example.com/hook", "https://[::1]/hook", "https://169.254.169.254/latest"])
def test_private_or_plain_http_hosts_blocked_in_production(fake_db, fake_context, ws_source, monkeypatch, url):
    wid, _sid = ws_source
    monkeypatch.setenv("APP_ENV", "production")
    fake_context.settings = config.reload()
    seen = _mock_client(monkeypatch, lambda r: httpx.Response(200))
    did = _delivery(fake_db, wid, url=url)
    out = webhooks.run_deliver_webhook(fake_context, did, now=NOW)
    assert out["status"] == "failed" and seen == []
    assert "gesperrt" in out["error"] or "https" in out["error"]


def test_assert_webhook_host_rules(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    s = config.reload()
    assert residency.assert_webhook_host("https://hooks.example.com/x", s) == "hooks.example.com"
    assert residency.assert_webhook_host("https://api.openai.com/x", s) == "api.openai.com"  # kein EU-Zwang für Webhooks
    for bad in ("http://hooks.example.com/x", "https://192.168.1.1/x", "https://127.0.0.1/x", "https://box/x", "https://", "ftp://hooks.example.com/x"):
        with pytest.raises(residency.ResidencyError):
            residency.assert_webhook_host(bad, s)
    monkeypatch.setenv("APP_ENV", "development")
    s = config.reload()
    assert residency.assert_webhook_host("http://localhost:4000/hook", s) == "localhost"
    assert residency.assert_webhook_host("https://10.0.0.5/hook", s) == "10.0.0.5"
    assert residency.is_private_host("10.1.2.3") and residency.is_private_host("printer.local") and not residency.is_private_host("hooks.example.com")


def test_webhook_client_hook_blocks_private_redirect_target(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    s = config.reload()
    with residency.webhook_client(s, transport=httpx.MockTransport(lambda r: httpx.Response(200))) as http:
        with pytest.raises(residency.ResidencyError):
            http.post("https://10.0.0.9/x", content=b"{}")
        assert http.post("https://hooks.example.com/x", content=b"{}").status_code == 200
