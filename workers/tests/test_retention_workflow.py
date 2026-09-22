"""RetentionWorkflow in der Temporal-Zeitraffer-Testumgebung (gemockte Activities) und ``ensure_schedules``.

Der Workflow-Test braucht das Temporal-Testbinary (Netz beim ersten Lauf): pytest -m network tests/test_retention_workflow.py
Der Schedule-Test läuft ohne Netz gegen einen Fake-Client.
"""

from __future__ import annotations

import uuid

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio import activity  # noqa: E402
from temporalio.client import ScheduleAlreadyRunningError  # noqa: E402
from temporalio.exceptions import ApplicationError  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from chopstr_worker import config, worker  # noqa: E402
from chopstr_worker.workflows.retention import RetentionParams, RetentionWorkflow  # noqa: E402

calls: list[tuple] = []


@activity.defn(name="find_expired")
async def fake_find_expired(now: str, limit: int) -> dict:
    calls.append(("find_expired", now, limit))
    return {"sources": ["s1", "s2", "s3"], "workspaces": ["w1"]}


@activity.defn(name="enqueue_deletion")
async def fake_enqueue(entity_id: str, reason: str, entity: str) -> str:
    calls.append(("enqueue_deletion", entity_id, reason, entity))
    return f"job-{entity_id}"


@activity.defn(name="delete_entity")
async def fake_delete(job_id: str) -> dict:
    calls.append(("delete_entity", job_id))
    if job_id == "job-s2":
        raise ApplicationError("Quelle s2 nicht gefunden", type="LookupError", non_retryable=True)
    return {"job_id": job_id, "status": "done"}


ACTIVITIES = [fake_find_expired, fake_enqueue, fake_delete]


async def _env():
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # Download des Test-Servers oder Start fehlgeschlagen (kein Netz)
        pytest.skip(f"Temporal-Testumgebung nicht verfügbar: {exc.__class__.__name__}")


@pytest.mark.network
async def test_retention_workflow_enqueues_and_deletes_sequentially():
    calls.clear()
    env = await _env()
    async with env:
        tq = f"tq-{uuid.uuid4().hex[:8]}"
        async with Worker(env.client, task_queue=tq, workflows=[RetentionWorkflow], activities=ACTIVITIES):
            result = await env.client.execute_workflow(
                RetentionWorkflow.run,
                RetentionParams(max_per_run=3, task_queue=tq),
                id=f"retention-{uuid.uuid4().hex[:8]}",
                task_queue=tq,
            )
    assert result.scanned_sources == 3 and result.scanned_workspaces == 1
    assert result.jobs == ["job-s1", "job-s2", "job-s3"]  # Limit 3: der Workspace wartet auf den nächsten Lauf
    assert result.done == 2 and result.failed == 1
    assert calls[0][0] == "find_expired" and calls[0][2] == 3
    order = [c for c in calls if c[0] != "find_expired"]
    assert order == [
        ("enqueue_deletion", "s1", "retention", "source"), ("delete_entity", "job-s1"),
        ("enqueue_deletion", "s2", "retention", "source"), ("delete_entity", "job-s2"),
        ("enqueue_deletion", "s3", "retention", "source"), ("delete_entity", "job-s3"),
    ]  # fmt: skip


class FakeScheduleClient:
    def __init__(self):
        self.created: dict[str, object] = {}

    async def create_schedule(self, id: str, schedule, **kwargs):
        if id in self.created:
            raise ScheduleAlreadyRunningError()
        self.created[id] = schedule


async def test_ensure_schedules_is_idempotent(monkeypatch):
    monkeypatch.setenv("RETENTION_CRON", "30 4 * * *")
    monkeypatch.setenv("RETENTION_TIMEZONE", "Europe/Berlin")
    s = config.reload()
    client = FakeScheduleClient()
    first = await worker.ensure_schedules(client, s)
    assert first["retention-daily"] == "created" and set(first) == {"retention-daily", "outbox-dispatch", "learning-nightly", "weekly-report"}
    assert set((await worker.ensure_schedules(client, s)).values()) == {"exists"}
    schedule = client.created["retention-daily"]
    assert list(schedule.spec.cron_expressions) == ["30 4 * * *"] and schedule.spec.time_zone_name == "Europe/Berlin"
    assert schedule.action.task_queue == s.task_queue_cpu and schedule.action.id == "retention-daily"


def test_worker_args_accept_ensure_schedules():
    args = worker.parse_args(["--queues", "cpu", "--ensure-schedules"])
    assert args.ensure_schedules is True and args.queues == "cpu"
    assert worker.parse_args([]).ensure_schedules is False
