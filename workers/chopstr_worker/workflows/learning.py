"""LearningWorkflow (Phase 5b): Schedule ``learning-nightly`` (Cron ``LEARNING_CRON``, Default 04:00 Europe/Vienna).

  find_learning_profiles -> je Markenprofil learn_brand_profile(brand_profile_id)

Sequenziell; ein Fehler bei einem Profil hält die anderen nicht auf und zählt in ``failed``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

SCHEDULE_ID = "learning-nightly"
WORKFLOW_ID = "learning-nightly"

RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))


@dataclass
class LearningParams:
    task_queue: str = ""  # leer: dieselbe Queue wie der Workflow


@dataclass
class LearningResult:
    profiles: int = 0
    learned: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[dict] = field(default_factory=list)


@workflow.defn(name="LearningWorkflow")
class LearningWorkflow:
    @workflow.run
    async def run(self, params: LearningParams | None = None) -> LearningResult:
        params = params or LearningParams()
        opts: dict = {"start_to_close_timeout": timedelta(minutes=10), "retry_policy": RETRY}
        if params.task_queue:
            opts["task_queue"] = params.task_queue
        result = LearningResult()
        profiles = list(await workflow.execute_activity("find_learning_profiles", **opts))
        result.profiles = len(profiles)
        for brand_profile_id in profiles:
            try:
                out = await workflow.execute_activity("learn_brand_profile", brand_profile_id, **opts)
            except ActivityError:
                result.failed += 1
                continue
            result.results.append(dict(out))
            if out.get("learned"):
                result.learned += 1
            else:
                result.skipped += 1
        return result


__all__ = ["SCHEDULE_ID", "WORKFLOW_ID", "LearningParams", "LearningResult", "LearningWorkflow"]
