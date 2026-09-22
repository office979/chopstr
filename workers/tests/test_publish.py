"""Publishing: Gates, interner Aufruf, Outbox und Decision Log, Metrik-Fenster mit Reward-Berechnung."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from chopstr_worker import config, internal_api, residency
from chopstr_worker.activities import publish

SEGS = [{"start": 0.0, "end": 30.0, "role": "body"}]


class FakeWeb:
    """Mock für /api/internal/*: zeichnet Aufrufe auf und antwortet je Pfad."""

    def __init__(self):
        self.calls: list[tuple[str, dict, dict]] = []
        self.publish_response: dict = {"status": "published", "external_id": "li-123", "external_url": "https://www.linkedin.com/posts/li-123", "error": None}
        self.metrics_response: dict = {"metrics": {"views": 1000, "likes": 50, "comments": 5, "shares": 2, "saves": 20, "follows": 10, "avg_watch_time_s": 12.5, "retention_curve": [1.0, 0.5]}}
        self.status_code = 200
        self.mail_response: dict = {"ok": True}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        self.calls.append((request.url.path, body, dict(request.headers)))
        if self.status_code != 200:
            return httpx.Response(self.status_code, json={"error": {"code": "x", "message": "kaputt"}})
        if request.url.path.endswith("/publish"):
            return httpx.Response(200, json=self.publish_response)
        if request.url.path.endswith("/metrics"):
            return httpx.Response(200, json=self.metrics_response)
        if request.url.path.endswith("/mail"):
            return httpx.Response(200, json=self.mail_response)
        return httpx.Response(404, json={"error": {"message": "unbekannt"}})


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()
    monkeypatch.setenv("INTERNAL_API_SECRET", "s3cret")
    monkeypatch.setenv("APP_INTERNAL_URL", "http://web:3000")
    config.reload()

    def _client(s=None, **kw):
        s = s or config.settings()
        return httpx.Client(transport=httpx.MockTransport(fake.handler), base_url="http://web:3000", headers={"X-Internal-Secret": s.internal_api_secret})

    monkeypatch.setattr(internal_api, "client", _client)
    return fake


@pytest.fixture
def pub(fake_db, fake_context, web):
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, title="Talk")
    cand = fake_db.add_candidate(sid, SEGS, human_verdict="accepted")
    cid = fake_db.add_clip(sid, cand, "linkedin", SEGS, status="rendered")
    conn = fake_db.add_connection(wid, "linkedin")
    pub_id = fake_db.add_publication(wid, cid, "linkedin", connection_id=conn, scheduled_for=datetime(2026, 9, 22, 8, 0, tzinfo=UTC))
    fake_context.settings = config.settings()
    return {"wid": wid, "pid": pid, "sid": sid, "cand": cand, "cid": cid, "conn": conn, "pub": pub_id}


def test_load_publication_shape(fake_context, pub):
    p = publish.load_publication(fake_context, pub["pub"])
    assert p["status"] == "scheduled" and p["scheduled_for"] == "2026-09-22T08:00:00+00:00" and p["clip_status"] == "rendered"
    assert p["workspace_id"] == pub["wid"] and p["brand_profile_id"] == pub["pid"] and p["candidate_id"] == pub["cand"]
    with pytest.raises(LookupError):
        publish.load_publication(fake_context, "fehlt")


def test_publish_success_writes_row_outbox_and_decision(fake_db, fake_context, pub, web):
    out = publish.run_publish_clip(fake_context, pub["pub"])
    assert out["status"] == "published" and out["external_id"] == "li-123"
    path, body, headers = web.calls[0]
    assert path == "/api/internal/publish" and body == {"publication_id": pub["pub"]} and headers["x-internal-secret"] == "s3cret"
    row = fake_db.publications[pub["pub"]]
    assert row["status"] == "published" and row["external_url"].startswith("https://www.linkedin.com/") and row["published_at"] is not None and row["error"] is None
    ev = fake_db.outbox_events[-1]
    assert ev["event"] == "publication.published" and ev["payload"]["external_id"] == "li-123" and ev["payload"]["clip_id"] == pub["cid"]
    dec = fake_db.decision_log[-1]
    assert dec["decision_type"] == "publish" and dec["actor_type"] == "system" and dec["chosen"]["status"] == "published"
    assert dec["clip_id"] == pub["cid"] and dec["brand_profile_id"] == pub["pid"] and dec["features"]["platform"] == "linkedin"
    # idempotent
    again = publish.run_publish_clip(fake_context, pub["pub"])
    assert again["skipped"] is True and len(web.calls) == 1


def test_gates_block_without_calling_web(fake_db, fake_context, pub, web):
    fake_db.clips[pub["cid"]]["status"] = "draft"
    next(c for c in fake_db.candidates if c["id"] == pub["cand"])["human_verdict"] = "rejected"
    out = publish.run_publish_clip(fake_context, pub["pub"])
    assert out["status"] == "failed" and len(out["gates"]) == 2 and web.calls == []
    assert "Clip ist nicht gerendert (Status draft)" in out["error"] and "Kandidat ist nicht angenommen (Urteil rejected)" in out["error"]
    assert fake_db.publications[pub["pub"]]["status"] == "failed"
    assert fake_db.outbox_events[-1]["event"] == "publication.failed"
    assert fake_db.decision_log[-1]["chosen"] == {"status": "failed", "reason": "gates"}
    assert fake_db.decision_log[-1]["features"]["gates_failed"] == out["gates"]


def test_guest_approval_gate(fake_db, fake_context, pub, web):
    fake_db.clips[pub["cid"]]["guest_approval_required"] = True
    out = publish.run_publish_clip(fake_context, pub["pub"])
    assert out["status"] == "failed" and "Gast-Freigabe fehlt (Entscheidung offen)" in out["error"]
    fake_db.add_guest_approval(pub["cid"], decision="changes")
    fake_db.publications[pub["pub"]]["status"] = "scheduled"
    assert "Entscheidung changes" in publish.run_publish_clip(fake_context, pub["pub"])["error"]
    fake_db.add_guest_approval(pub["cid"], decision="approved")
    fake_db.publications[pub["pub"]]["status"] = "scheduled"
    assert publish.run_publish_clip(fake_context, pub["pub"])["status"] == "published"


def test_provider_failure_and_web_error(fake_db, fake_context, pub, web):
    web.publish_response = {"status": "failed", "error": "Token abgelaufen"}
    out = publish.run_publish_clip(fake_context, pub["pub"])
    assert out["status"] == "failed" and out["error"] == "Token abgelaufen"
    assert fake_db.publications[pub["pub"]]["error"] == "Token abgelaufen"
    assert fake_db.outbox_events[-1]["event"] == "publication.failed"
    fake_db.publications[pub["pub"]]["status"] = "scheduled"
    web.status_code = 500
    with pytest.raises(internal_api.InternalApiError, match="antwortete mit 500"):
        publish.run_publish_clip(fake_context, pub["pub"])
    assert fake_db.publications[pub["pub"]]["status"] == "failed" and "Web-App nicht erreichbar" in fake_db.publications[pub["pub"]]["error"]


def test_manual_and_cancel(fake_db, fake_context, pub, web):
    fake_db.publications[pub["pub"]]["status"] = "manual"
    assert publish.run_publish_clip(fake_context, pub["pub"])["skipped"] is True and web.calls == []
    fake_db.publications[pub["pub"]]["status"] = "scheduled"
    out = publish.run_cancel_publication(fake_context, pub["pub"])
    assert out["cancelled"] is True and fake_db.publications[pub["pub"]]["error"] == "Veröffentlichung abgebrochen"
    assert publish.run_cancel_publication(fake_context, pub["pub"])["cancelled"] is False


# -- Reward --------------------------------------------------------------------------------------
def test_compute_reward_without_history_and_with_missing_metrics():
    full = publish.compute_reward({"views": 1000, "follows": 10, "saves": 20}, [])
    assert full["follows_per_1k"] == 10.0 and full["saves_per_1k"] == 20.0
    assert full["account_median_views"] is None and full["outlier_score"] is None
    assert full["norms"] == {"follows": 1.0, "saves": 1.0, "outlier": None}
    assert full["reward"] == 1.0  # nur follows und saves, neu gewichtet auf 0,5 und 0,3

    partial = publish.compute_reward({"views": 1000, "follows": None, "saves": 20}, [])
    assert partial["follows_per_1k"] is None and partial["saves_per_1k"] == 20.0 and partial["reward"] == 1.0

    nothing = publish.compute_reward({"views": None, "follows": None, "saves": None}, [])
    assert nothing["reward"] is None and nothing["follows_per_1k"] is None

    zero_views = publish.compute_reward({"views": 0, "follows": 3}, [])
    assert zero_views["follows_per_1k"] is None and zero_views["reward"] is None


def test_compute_reward_normalizes_on_account_and_caps():
    history = [(1000, 5.0, 10.0), (2000, 10.0, 20.0), (3000, 15.0, 30.0)]  # Mediane: 2000 Views, 10 f/1k, 20 s/1k
    out = publish.compute_reward({"views": 4000, "follows": 80, "saves": 40}, history)
    assert out["follows_per_1k"] == 20.0 and out["saves_per_1k"] == 10.0
    assert out["account_median_views"] == 2000.0 and out["outlier_score"] == 2.0
    assert out["norms"] == {"follows": 2.0, "saves": 0.5, "outlier": 2.0}
    assert out["reward"] == round(0.5 * 2.0 + 0.3 * 0.5 + 0.2 * 2.0, 4)
    capped = publish.compute_reward({"views": 100000, "follows": 100000, "saves": 0}, history)
    assert capped["norms"]["follows"] == 3.0 and capped["norms"]["outlier"] == 3.0 and capped["norms"]["saves"] == 0.0
    assert capped["reward"] == round(0.5 * 3 + 0.3 * 0 + 0.2 * 3, 4)
    # Median 0 in der Historie: Wert > 0 zählt als Ausreißer (gedeckelt), sonst neutral
    assert publish.compute_reward({"views": 10, "follows": 1}, [(0, 0.0, None)])["norms"]["follows"] == 3.0
    assert publish.compute_reward({"views": 10, "follows": 0}, [(0, 0.0, None)])["norms"]["follows"] == 1.0


def test_fetch_metrics_writes_feedback_with_account_median_and_upserts(fake_db, fake_context, pub, web):
    publish.run_publish_clip(fake_context, pub["pub"])
    # Historie desselben Accounts (Verbindung), eine fremde Verbindung, ein anderes Fenster
    for views in (500, 1500, 2500):
        other_clip = fake_db.add_clip(pub["sid"], pub["cand"], "linkedin", SEGS, status="rendered")
        other_pub = fake_db.add_publication(pub["wid"], other_clip, "linkedin", connection_id=pub["conn"], status="published")
        fake_db.add_feedback(pub["wid"], other_clip, other_pub, views=views, follows_per_1k=5.0, saves_per_1k=10.0, reward=1.0)
    foreign_pub = fake_db.add_publication(pub["wid"], pub["cid"], "linkedin", connection_id=fake_db.add_connection(pub["wid"]), status="published")
    fake_db.add_feedback(pub["wid"], pub["cid"], foreign_pub, views=999999, follows_per_1k=99.0, saves_per_1k=99.0)
    fake_db.add_feedback(pub["wid"], pub["cid"], foreign_pub, metric_window="6h", views=999999)

    out = publish.run_fetch_metrics(fake_context, pub["pub"], "48h")
    assert web.calls[-1][0] == "/api/internal/metrics" and web.calls[-1][1] == {"publication_id": pub["pub"], "window": "48h"}
    assert out["follows_per_1k"] == 10.0 and out["saves_per_1k"] == 20.0 and out["account_median_views"] == 1500.0
    assert out["outlier_score"] == round(1000 / 1500, 4) and out["history_n"] == 3
    assert out["norms"] == {"follows": 2.0, "saves": 2.0, "outlier": round(1000 / 1500, 4)}
    row = next(f for f in fake_db.performance_feedback if f["publication_id"] == pub["pub"])
    assert row["metric_window"] == "48h" and row["views"] == 1000 and row["follows"] == 10 and row["retention_curve"] == [1.0, 0.5]
    assert row["reward"] == out["reward"] and row["clip_id"] == pub["cid"] and row["platform"] == "linkedin"
    p = fake_db.publications[pub["pub"]]
    assert set(p["metrics"]) == {"at_48h"} and p["metrics"]["at_48h"]["views"] == 1000 and p["metrics_fetched_at"] is not None

    web.metrics_response = {"metrics": {"views": 2000, "follows": None, "saves": None}}
    out2 = publish.run_fetch_metrics(fake_context, pub["pub"], "48h")
    rows = [f for f in fake_db.performance_feedback if f["publication_id"] == pub["pub"]]
    assert len(rows) == 1 and rows[0]["views"] == 2000 and rows[0]["follows"] is None and rows[0]["follows_per_1k"] is None
    assert out2["norms"]["follows"] is None and out2["reward"] == out2["norms"]["outlier"]  # nur Ausreißer-Anteil
    publish.run_fetch_metrics(fake_context, pub["pub"], "7d")
    assert set(fake_db.publications[pub["pub"]]["metrics"]) == {"at_48h", "at_7d"}


def test_fetch_metrics_requires_published_and_known_window(fake_context, pub):
    with pytest.raises(RuntimeError, match="nicht veröffentlicht"):
        publish.run_fetch_metrics(fake_context, pub["pub"], "6h")
    with pytest.raises(ValueError):
        publish.run_fetch_metrics(fake_context, pub["pub"], "1h")


# -- Interner Client -----------------------------------------------------------------------------
def test_internal_api_host_is_on_residency_allowlist(monkeypatch):
    monkeypatch.setenv("APP_INTERNAL_URL", "http://web:3000")
    s = config.reload()
    assert "web" in residency.allowed_hosts(s)
    assert residency.assert_eu_host("http://web:3000/api/internal/publish", s) == "web"


def test_internal_api_requires_secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SECRET", "")
    s = config.reload()
    with pytest.raises(RuntimeError, match="INTERNAL_API_SECRET"):
        internal_api.client(s)


def test_internal_api_mail_and_errors(web):
    assert internal_api.mail(["a@example.com"], "Betreff", "Text") is True
    assert web.calls[-1][1] == {"to": ["a@example.com"], "subject": "Betreff", "text": "Text"}
    assert internal_api.mail([], "x", "y") is False
    with pytest.raises(internal_api.InternalApiError):
        internal_api.post("unknown", {})
    with pytest.raises(ValueError):
        internal_api.metrics("p", "1h")
