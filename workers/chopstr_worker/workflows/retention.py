"""RetentionWorkflow: täglicher Lauf über den Temporal-Schedule ``retention-daily`` (PHASE4.md Abschnitt 7).

  find_expired(now) -> je Clip mit abgelaufener eigener Frist: enqueue_deletion(clip_id, 'retention', 'clip')
                       -> delete_entity(job_id)
                    -> je Quelle: enqueue_deletion(source_id, 'retention') -> delete_entity(job_id)
                    -> je Workspace nach der Karenz: enqueue_deletion(workspace_id, 'retention', 'workspace')
                       -> delete_entity(job_id)

Clips zuerst, und zwar mit Absicht: Seit Migration 0006 haben Renderings eine eigene, längere Frist
(``clips.delete_after``, ``workspaces.render_retention_days``). Sind Quelle und Clip am selben Tag fällig,
würde die Quellenlöschung die Clipzeile mitnehmen und der danach eingereihte Clip-Job liefe ins Leere
(``LookupError``, nicht wiederholbar). Umgekehrt ist es harmlos: ``delete_entity`` lässt die Clipzeile als
Nachweis stehen, die Quellenlöschung räumt sie anschließend weg.

Sequenziell, höchstens ``max_per_run`` Jobs pro Lauf (Default 50). Ein fehlgeschlagener Job (die Activity
setzt ihn auf ``failed``) hält die anderen nicht auf; er zählt in ``failed`` des Ergebnisses.
Deterministisch: die Zeit kommt aus ``workflow.now()``, Queues als Parameter (leer = Queue des Workflows).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

SCHEDULE_ID = "retention-daily"
WORKFLOW_ID = "retention-daily"

SCAN_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))
DELETE_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30), non_retryable_error_types=["LookupError", "ValueError"])


@dataclass
class RetentionParams:
    max_per_run: int = 50
    task_queue: str = ""  # leer: dieselbe Queue wie der Workflow


@dataclass
class RetentionResult:
    scanned_sources: int = 0
    scanned_workspaces: int = 0
    scanned_clips: int = 0
    jobs: list[str] = field(default_factory=list)
    done: int = 0
    failed: int = 0


@workflow.defn(name="RetentionWorkflow")
class RetentionWorkflow:
    def __init__(self) -> None:
        self.result = RetentionResult()

    @workflow.query
    def progress(self) -> RetentionResult:
        return self.result

    @workflow.run
    async def run(self, params: RetentionParams | None = None) -> RetentionResult:
        params = params or RetentionParams()
        opts: dict = {"start_to_close_timeout": timedelta(minutes=5), "retry_policy": SCAN_RETRY}
        delete_opts: dict = {
            "start_to_close_timeout": timedelta(minutes=30),
            "heartbeat_timeout": timedelta(minutes=5),
            "retry_policy": DELETE_RETRY,
        }
        if params.task_queue:
            opts["task_queue"] = params.task_queue
            delete_opts["task_queue"] = params.task_queue

        now = workflow.now().isoformat()
        expired = await workflow.execute_activity("find_expired", args=[now, params.max_per_run], **opts)
        sources = list(expired.get("sources") or [])
        clips = list(expired.get("clips") or [])
        workspaces = list(expired.get("workspaces") or [])
        self.result.scanned_sources = len(sources)
        self.result.scanned_clips = len(clips)
        self.result.scanned_workspaces = len(workspaces)

        queue = (
            [(cid, "clip") for cid in clips]
            + [(sid, "source") for sid in sources]
            + [(wid, "workspace") for wid in workspaces]
        )
        for entity_id, entity in queue[: params.max_per_run]:
            job_id = await workflow.execute_activity("enqueue_deletion", args=[entity_id, "retention", entity], **opts)
            self.result.jobs.append(job_id)
            try:
                await workflow.execute_activity("delete_entity", job_id, **delete_opts)
                self.result.done += 1
            except ActivityError:
                self.result.failed += 1
        return self.result


__all__ = ["SCHEDULE_ID", "WORKFLOW_ID", "RetentionParams", "RetentionResult", "RetentionWorkflow"]
