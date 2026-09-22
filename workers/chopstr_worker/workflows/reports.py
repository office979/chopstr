"""WeeklyReportWorkflow (Phase 5b): Schedule ``weekly-report`` (Cron ``WEEKLY_REPORT_CRON``, Montag 07:00 Europe/Vienna).

  find_report_workspaces -> je Workspace build_weekly_report(workspace_id, week_start)

``week_start`` ist der Montag der Vorwoche (aus ``workflow.now()``), per Parameter überschreibbar
(ISO-Datum). Ein Fehler bei einem Workspace hält die anderen nicht auf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

SCHEDULE_ID = "weekly-report"
WORKFLOW_ID = "weekly-report"

RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))


@dataclass
class WeeklyReportParams:
    week_start: str = ""  # leer: Montag der Vorwoche
    task_queue: str = ""


@dataclass
class WeeklyReportResult:
    week_start: str = ""
    workspaces: int = 0
    built: int = 0
    sent: int = 0
    failed: int = 0
    results: list[dict] = field(default_factory=list)


@workflow.defn(name="WeeklyReportWorkflow")
class WeeklyReportWorkflow:
    @workflow.run
    async def run(self, params: WeeklyReportParams | None = None) -> WeeklyReportResult:
        params = params or WeeklyReportParams()
        opts: dict = {"start_to_close_timeout": timedelta(minutes=10), "retry_policy": RETRY}
        if params.task_queue:
            opts["task_queue"] = params.task_queue
        week_start = params.week_start or _previous_monday(workflow.now().date())
        result = WeeklyReportResult(week_start=week_start)
        workspaces = list(await workflow.execute_activity("find_report_workspaces", **opts))
        result.workspaces = len(workspaces)
        for workspace_id in workspaces:
            try:
                out = await workflow.execute_activity("build_weekly_report", args=[workspace_id, week_start], **opts)
            except ActivityError:
                result.failed += 1
                continue
            result.built += 1
            if out.get("sent"):
                result.sent += 1
            result.results.append(dict(out))
        return result


def _previous_monday(d) -> str:
    monday = d - timedelta(days=d.weekday())
    return (monday - timedelta(days=7)).isoformat()


__all__ = ["SCHEDULE_ID", "WORKFLOW_ID", "WeeklyReportParams", "WeeklyReportResult", "WeeklyReportWorkflow"]
