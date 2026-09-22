"""DeletionWorkflow: führt genau einen Lösch-Job sofort aus (PHASE4.md Abschnitt 7).

Die Web-App startet ihn nach einer Nutzeranfrage (Quelle, Clip, Markenprofil oder Workspace löschen),
Workflow-ID ``deletion-<job_id>``. Der tägliche ``RetentionWorkflow`` holt alle Jobs ab, die niemand
gestartet hat. Ein Job ist idempotent: die Activity ``delete_entity`` überspringt bereits gelöschte Keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

DELETE_RETRY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    non_retryable_error_types=["LookupError", "ValueError"],
)


@dataclass
class DeletionParams:
    job_id: str
    task_queue: str = ""  # leer: dieselbe Queue wie der Workflow


@workflow.defn(name="DeletionWorkflow")
class DeletionWorkflow:
    @workflow.run
    async def run(self, params: DeletionParams) -> dict:
        opts: dict = dict(start_to_close_timeout=timedelta(minutes=30), retry_policy=DELETE_RETRY)
        if params.task_queue:
            opts["task_queue"] = params.task_queue
        return await workflow.execute_activity("delete_entity", params.job_id, **opts)


__all__ = ["DELETE_RETRY", "DeletionParams", "DeletionWorkflow"]
