"""Phase-5-Workflows in der Zeitraffer-Testumgebung (gemockte Activities): Outbox, Publish, Learning, Wochenreport.

Braucht das Temporal-Testbinary (Netz beim ersten Lauf): pytest -m network tests/test_phase5_workflows.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio import activity  # noqa: E402
from temporalio.client import ScheduleOverlapPolicy  # noqa: E402
from temporalio.exceptions import ApplicationError  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from chopstr_worker import config, worker  # noqa: E402
from chopstr_worker.workflows.learning import LearningParams, LearningWorkflow  # noqa: E402
from chopstr_worker.workflows.outbox import OutboxParams, OutboxWorkflow  # noqa: E402
from chopstr_worker.workflows.publish import PublishParams, PublishWorkflow  # noqa: E402
from chopstr_worker.workflows.reports import WeeklyReportParams, WeeklyReportWorkflow  # noqa: E402

pytestmark = pytest.mark.network

calls: list[tuple] = []


async def _env():
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # Download des Test-Servers oder Start fehlgeschlagen (kein Netz)
        pytest.skip(f"Temporal-Testumgebung nicht verfügbar: {exc.__class__.__name__}")


# -- Outbox --------------------------------------------------------------------------------------
@activity.defn(name="dispatch_outbox")
async def fake_dispatch(limit: int) -> dict:
    calls.append(("dispatch_outbox", limit))
    return {"events": 2, "deliveries": 3}


@activity.defn(name="find_due_deliveries")
async def fake_due(now: str, limit: int) -> list[str]:
    calls.append(("find_due_deliveries", limit))
    return ["d-ok", "d-retry", "d-boom"]


@activity.defn(name="deliver_webhook")
async def fake_deliver(delivery_id: str) -> dict:
    calls.append(("deliver_webhook", delivery_id))
    if delivery_id == "d-boom":
        raise ApplicationError("Zustellung nicht gefunden", type="LookupError", non_retryable=True)
    return {"status": "delivered" if delivery_id == "d-ok" else "pending"}


async def test_outbox_workflow_dispatches_then_delivers_all_due():
    calls.clear()
    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=tq, workflows=[OutboxWorkflow], activities=[fake_dispatch, fake_due, fake_deliver]):
            result = await env.client.execute_workflow(OutboxWorkflow.run, OutboxParams(limit=50, task_queue=tq), id=f"outbox-{uuid.uuid4().hex[:8]}", task_queue=tq)
    assert (result.events, result.deliveries, result.due) == (2, 3, 3)
    assert (result.delivered, result.pending, result.errors, result.failed) == (1, 1, 1, 0)
    assert calls[0] == ("dispatch_outbox", 50) and calls[1] == ("find_due_deliveries", 50)
    assert sorted(c[1] for c in calls if c[0] == "deliver_webhook") == ["d-boom", "d-ok", "d-retry"]


# -- Publish -------------------------------------------------------------------------------------
class PublishFakes:
    def __init__(self, scheduled_for: str | None, publish_status: str = "published", metrics_fail: set[str] | None = None):
        self.scheduled_for = scheduled_for
        self.publish_status = publish_status
        self.metrics_fail = metrics_fail or set()
        self.calls: list[tuple] = []

    def activities(self):
        fakes = self

        @activity.defn(name="load_publication")
        async def load_publication(publication_id: str) -> dict:
            fakes.calls.append(("load_publication", publication_id))
            return {"id": publication_id, "status": "scheduled", "scheduled_for": fakes.scheduled_for, "published_at": None, "platform": "linkedin"}

        @activity.defn(name="publish_clip")
        async def publish_clip(publication_id: str) -> dict:
            fakes.calls.append(("publish_clip", publication_id, activity.info().attempt))
            if fakes.publish_status == "boom":
                raise RuntimeError("Web-App nicht erreichbar")
            return {"publication_id": publication_id, "status": fakes.publish_status, "error": None if fakes.publish_status == "published" else "Token abgelaufen", "published_at": datetime.now(UTC).isoformat()}

        @activity.defn(name="fetch_metrics")
        async def fetch_metrics(publication_id: str, window: str) -> dict:
            fakes.calls.append(("fetch_metrics", window))
            if window in fakes.metrics_fail:
                raise ApplicationError("Metriken nicht verfügbar", type="ValueError", non_retryable=True)
            return {"publication_id": publication_id, "window": window, "reward": 1.25}

        @activity.defn(name="cancel_publication")
        async def cancel_publication(publication_id: str) -> dict:
            fakes.calls.append(("cancel_publication", publication_id))
            return {"cancelled": True}

        return [load_publication, publish_clip, fetch_metrics, cancel_publication]


async def test_publish_workflow_waits_publishes_and_fetches_three_windows():
    env = await _env()
    async with env:
        # Zeitpunkte relativ zur Uhr der Testumgebung (sie springt beim Zeitraffer weit voraus)
        fakes = PublishFakes((await env.get_current_time() + timedelta(hours=3)).isoformat(), metrics_fail={"48h"})
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=tq, workflows=[PublishWorkflow], activities=fakes.activities()):
            result = await env.client.execute_workflow(PublishWorkflow.run, PublishParams(publication_id="p1", task_queue=tq), id="publish-p1", task_queue=tq)
    assert result["status"] == "published"
    assert result["metrics"] == {"6h": {"ok": True, "reward": 1.25}, "48h": {"ok": False, "error": "Metriken nicht verfügbar"}, "7d": {"ok": True, "reward": 1.25}}
    assert [c[0] for c in fakes.calls] == ["load_publication", "publish_clip", "fetch_metrics", "fetch_metrics", "fetch_metrics"]
    assert [c[1] for c in fakes.calls if c[0] == "fetch_metrics"] == ["6h", "48h", "7d"]


async def test_publish_workflow_cancel_and_reschedule_signals():
    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        fakes = PublishFakes((await env.get_current_time() + timedelta(days=2)).isoformat())
        async with Worker(env.client, task_queue=tq, workflows=[PublishWorkflow], activities=fakes.activities()):
            handle = await env.client.start_workflow(PublishWorkflow.run, PublishParams(publication_id="p2", task_queue=tq), id="publish-p2", task_queue=tq)
            await env.sleep(timedelta(minutes=1))
            assert await handle.query(PublishWorkflow.stage) == "waiting"
            await handle.signal(PublishWorkflow.cancel)
            result = await handle.result()
        assert result == {"publication_id": "p2", "status": "cancelled"}
        assert [c[0] for c in fakes.calls] == ["load_publication", "cancel_publication"]

        fakes2 = PublishFakes((await env.get_current_time() + timedelta(days=30)).isoformat())
        async with Worker(env.client, task_queue=tq, workflows=[PublishWorkflow], activities=fakes2.activities()):
            handle = await env.client.start_workflow(PublishWorkflow.run, PublishParams(publication_id="p3", task_queue=tq), id="publish-p3", task_queue=tq)
            await env.sleep(timedelta(minutes=1))
            assert await handle.query(PublishWorkflow.stage) == "waiting"
            await handle.signal(PublishWorkflow.reschedule, (await env.get_current_time() + timedelta(minutes=5)).isoformat())
            result = await handle.result()
            assert await handle.query(PublishWorkflow.stage) == "done"  # Query braucht einen laufenden Worker
        assert result["status"] == "published" and [c[0] for c in fakes2.calls][:2] == ["load_publication", "publish_clip"]
        assert [c[1] for c in fakes2.calls if c[0] == "fetch_metrics"] == ["6h", "48h", "7d"]


async def test_publish_workflow_stops_after_failed_publish_and_retries_transport_errors():
    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        fakes = PublishFakes(None, publish_status="failed")
        async with Worker(env.client, task_queue=tq, workflows=[PublishWorkflow], activities=fakes.activities()):
            result = await env.client.execute_workflow(PublishWorkflow.run, PublishParams(publication_id="p4", task_queue=tq), id="publish-p4", task_queue=tq)
        assert result["status"] == "failed" and result["error"] == "Token abgelaufen"
        assert [c[0] for c in fakes.calls] == ["load_publication", "publish_clip"]

        boom = PublishFakes(None, publish_status="boom")
        async with Worker(env.client, task_queue=tq, workflows=[PublishWorkflow], activities=boom.activities()):
            with pytest.raises(Exception):  # noqa: B017 - WorkflowFailureError nach drei Versuchen
                await env.client.execute_workflow(PublishWorkflow.run, PublishParams(publication_id="p5", task_queue=tq), id="publish-p5", task_queue=tq)
        assert [c[2] for c in boom.calls if c[0] == "publish_clip"] == [1, 2, 3]


# -- Learning und Wochenreport -------------------------------------------------------------------
async def test_learning_and_weekly_report_workflows():
    calls.clear()

    @activity.defn(name="find_learning_profiles")
    async def find_profiles() -> list[str]:
        return ["bp1", "bp2", "bp3"]

    @activity.defn(name="learn_brand_profile")
    async def learn(brand_profile_id: str) -> dict:
        calls.append(("learn", brand_profile_id))
        if brand_profile_id == "bp3":
            raise ApplicationError("kaputt", type="LookupError", non_retryable=True)
        return {"brand_profile_id": brand_profile_id, "learned": brand_profile_id == "bp1", "n": 30, "r2": 0.7, "hook_patterns": 5}

    @activity.defn(name="find_report_workspaces")
    async def find_ws() -> list[str]:
        return ["ws1", "ws2"]

    @activity.defn(name="build_weekly_report")
    async def build(workspace_id: str, week_start: str) -> dict:
        calls.append(("report", workspace_id, week_start))
        return {"report_id": f"r-{workspace_id}", "clips": 3, "sent": workspace_id == "ws1"}

    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=tq, workflows=[LearningWorkflow, WeeklyReportWorkflow], activities=[find_profiles, learn, find_ws, build]):
            learned = await env.client.execute_workflow(LearningWorkflow.run, LearningParams(task_queue=tq), id=f"learning-{uuid.uuid4().hex[:8]}", task_queue=tq)
            report = await env.client.execute_workflow(WeeklyReportWorkflow.run, WeeklyReportParams(week_start="2026-09-14", task_queue=tq), id=f"report-{uuid.uuid4().hex[:8]}", task_queue=tq)
            auto = await env.client.execute_workflow(WeeklyReportWorkflow.run, WeeklyReportParams(task_queue=tq), id=f"report-{uuid.uuid4().hex[:8]}", task_queue=tq)
    assert (learned.profiles, learned.learned, learned.skipped, learned.failed) == (3, 1, 1, 1)
    assert (report.workspaces, report.built, report.sent, report.failed) == (2, 2, 1, 0) and report.week_start == "2026-09-14"
    assert [c for c in calls if c[0] == "report"][:2] == [("report", "ws1", "2026-09-14"), ("report", "ws2", "2026-09-14")]
    assert datetime.fromisoformat(auto.week_start).weekday() == 0  # Montag der Vorwoche


# -- Schedules -----------------------------------------------------------------------------------
class FakeScheduleClient:
    def __init__(self):
        self.created: dict[str, object] = {}

    async def create_schedule(self, id: str, schedule, **kwargs):
        from temporalio.client import ScheduleAlreadyRunningError

        if id in self.created:
            raise ScheduleAlreadyRunningError()
        self.created[id] = schedule


async def test_ensure_schedules_creates_phase5_schedules(monkeypatch):
    monkeypatch.setenv("OUTBOX_INTERVAL_S", "45")
    monkeypatch.setenv("WEEKLY_REPORT_CRON", "0 7 * * 1")
    monkeypatch.setenv("LEARNING_CRON", "15 4 * * *")
    s = config.reload()
    client = FakeScheduleClient()
    out = await worker.ensure_schedules(client, s)
    assert out == {"retention-daily": "created", "outbox-dispatch": "created", "learning-nightly": "created", "weekly-report": "created"}
    outbox = client.created["outbox-dispatch"]
    assert outbox.spec.intervals[0].every == timedelta(seconds=45) and outbox.action.id == "outbox-dispatch"
    assert list(client.created["weekly-report"].spec.cron_expressions) == ["0 7 * * 1"]
    assert list(client.created["learning-nightly"].spec.cron_expressions) == ["15 4 * * *"]
    assert client.created["weekly-report"].spec.time_zone_name == "Europe/Vienna"
    assert all(sch.policy.overlap == ScheduleOverlapPolicy.SKIP for sch in client.created.values())
