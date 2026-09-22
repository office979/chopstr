"""DeletionWorkflow ruft genau einmal delete_entity mit der Job-ID auf (Zeitraffer-Testumgebung)."""

from __future__ import annotations

import uuid

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio import activity  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from chopstr_worker.workflows.deletion import DeletionParams, DeletionWorkflow  # noqa: E402

pytestmark = pytest.mark.network


@pytest.mark.asyncio
async def test_deletion_workflow_runs_delete_entity_once():
    calls: list[str] = []

    @activity.defn(name="delete_entity")
    async def delete_entity(job_id: str) -> dict:
        calls.append(job_id)
        return {"status": "done", "keys_deleted": [], "rows_deleted": {}}

    job_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker = Worker(env.client, task_queue="test-cpu", workflows=[DeletionWorkflow], activities=[delete_entity])
        async with worker:
            out = await env.client.execute_workflow(
                DeletionWorkflow.run, DeletionParams(job_id=job_id), id=f"deletion-{job_id}", task_queue="test-cpu"
            )
    assert calls == [job_id]
    assert out["status"] == "done"
