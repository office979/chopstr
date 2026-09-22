"""OutboxWorkflow (Phase 5a): Schedule ``outbox-dispatch`` alle ``OUTBOX_INTERVAL_S`` Sekunden.

  dispatch_outbox(limit) -> find_due_deliveries(now, limit) -> deliver_webhook(id) je fällige Zustellung

Die Zustellungen laufen parallel; ein Fehlschlag hält die anderen nicht auf. Backoff und Höchstzahl der
Versuche liegen in der Datenbank (``webhook_deliveries.next_attempt_at``), deshalb ohne Temporal-Retry
für ``deliver_webhook``. Deterministisch: Zeit aus ``workflow.now()``, Queue als Parameter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

SCHEDULE_ID = "outbox-dispatch"
WORKFLOW_ID = "outbox-dispatch"

DISPATCH_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5))
DELIVER_RETRY = RetryPolicy(maximum_attempts=1)


@dataclass
class OutboxParams:
    limit: int = 200
    task_queue: str = ""  # leer: dieselbe Queue wie der Workflow


@dataclass
class OutboxResult:
    events: int = 0
    deliveries: int = 0
    due: int = 0
    delivered: int = 0
    pending: int = 0
    failed: int = 0
    errors: int = 0


@workflow.defn(name="OutboxWorkflow")
class OutboxWorkflow:
    @workflow.run
    async def run(self, params: OutboxParams | None = None) -> OutboxResult:
        params = params or OutboxParams()
        opts: dict = {"start_to_close_timeout": timedelta(minutes=2), "retry_policy": DISPATCH_RETRY}
        deliver_opts: dict = {"start_to_close_timeout": timedelta(minutes=1), "retry_policy": DELIVER_RETRY}
        if params.task_queue:
            opts["task_queue"] = params.task_queue
            deliver_opts["task_queue"] = params.task_queue

        result = OutboxResult()
        dispatched = await workflow.execute_activity("dispatch_outbox", params.limit, **opts)
        result.events = int(dispatched.get("events", 0))
        result.deliveries = int(dispatched.get("deliveries", 0))

        now = workflow.now().isoformat()
        due = list(await workflow.execute_activity("find_due_deliveries", args=[now, params.limit], **opts))
        result.due = len(due)
        outs = await asyncio.gather(
            *[workflow.execute_activity("deliver_webhook", delivery_id, **deliver_opts) for delivery_id in due],
            return_exceptions=True,
        )
        for out in outs:
            if isinstance(out, BaseException):
                result.errors += 1
                continue
            status = str(out.get("status", ""))
            if status == "delivered":
                result.delivered += 1
            elif status == "failed":
                result.failed += 1
            else:
                result.pending += 1
        return result


__all__ = ["SCHEDULE_ID", "WORKFLOW_ID", "OutboxParams", "OutboxResult", "OutboxWorkflow"]
