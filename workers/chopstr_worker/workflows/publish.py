"""PublishWorkflow (Phase 5b): Workflow-ID ``publish-<publication_id>``, gestartet von der Web-App.

  load_publication -> Timer bis scheduled_for -> publish_clip -> Timer 6 h / 48 h / 7 d -> fetch_metrics

Signale: ``cancel`` (nur vor dem Publish wirksam, ruft ``cancel_publication``) und ``reschedule(iso)``
(neuer Zeitpunkt, Timer wird neu gesetzt). Ist die Publikation beim Start schon ``published``, werden nur
die Metrik-Fenster nachgeholt. Fehler in ``fetch_metrics`` (nach drei Versuchen) beenden den Workflow
nicht; das Fenster wird im Ergebnis als fehlgeschlagen vermerkt. Deterministisch: Zeit aus ``workflow.now()``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

METRIC_WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("6h", timedelta(hours=6)),
    ("48h", timedelta(hours=48)),
    ("7d", timedelta(days=7)),
)
NON_RETRYABLE = ["LookupError", "ValueError", "ResidencyError"]
LOAD_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5), non_retryable_error_types=NON_RETRYABLE)
PUBLISH_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30), non_retryable_error_types=NON_RETRYABLE)
METRICS_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=1), non_retryable_error_types=NON_RETRYABLE)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class PublishParams:
    publication_id: str
    task_queue: str = ""  # leer: dieselbe Queue wie der Workflow


@dataclass
class PublishState:
    stage: str = "queued"
    cancelled: bool = False
    scheduled_for: str | None = None
    reschedules: int = 0
    publish: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)


@workflow.defn(name="PublishWorkflow")
class PublishWorkflow:
    def __init__(self) -> None:
        self.state = PublishState()

    # -- Signale und Queries -------------------------------------------------------------------
    @workflow.signal
    def cancel(self) -> None:
        if self.state.stage in ("queued", "waiting"):
            self.state.cancelled = True

    @workflow.signal
    def reschedule(self, scheduled_for: str) -> None:
        if self.state.stage in ("queued", "waiting"):
            self.state.scheduled_for = scheduled_for
            self.state.reschedules += 1

    @workflow.query
    def stage(self) -> str:
        return self.state.stage

    # -- Ablauf --------------------------------------------------------------------------------
    @workflow.run
    async def run(self, params: PublishParams) -> dict:
        pid = params.publication_id
        opts: dict = {"start_to_close_timeout": timedelta(minutes=2), "retry_policy": LOAD_RETRY}
        publish_opts: dict = {"start_to_close_timeout": timedelta(minutes=10), "retry_policy": PUBLISH_RETRY}
        metrics_opts: dict = {"start_to_close_timeout": timedelta(minutes=5), "retry_policy": METRICS_RETRY}
        if params.task_queue:
            for o in (opts, publish_opts, metrics_opts):
                o["task_queue"] = params.task_queue

        pub = await workflow.execute_activity("load_publication", pid, **opts)
        published_at = _parse(pub.get("published_at"))

        if pub.get("status") != "published":
            self.state.stage = "waiting"
            if self.state.scheduled_for is None:
                self.state.scheduled_for = pub.get("scheduled_for")
            await self._wait_until_due()
            if self.state.cancelled:
                self.state.stage = "cancelled"
                await workflow.execute_activity("cancel_publication", pid, **opts)
                return {"publication_id": pid, "status": "cancelled"}

            self.state.stage = "publishing"
            result = await workflow.execute_activity("publish_clip", pid, **publish_opts)
            self.state.publish = dict(result)
            if result.get("status") != "published":
                self.state.stage = "failed"
                return {"publication_id": pid, "status": str(result.get("status", "failed")), "error": result.get("error"), "publish": result}
            published_at = _parse(result.get("published_at")) or workflow.now()

        published_at = published_at or workflow.now()
        self.state.stage = "metrics"
        for window, delta in METRIC_WINDOWS:
            wait = (published_at + delta) - workflow.now()
            if wait > timedelta(0):
                await asyncio.sleep(wait.total_seconds())
            try:
                out = await workflow.execute_activity("fetch_metrics", args=[pid, window], **metrics_opts)
                self.state.metrics[window] = {"ok": True, "reward": out.get("reward")}
            except ActivityError as exc:
                cause = exc.cause
                message = getattr(cause, "message", None) or str(cause or exc)
                self.state.metrics[window] = {"ok": False, "error": str(message)[:200]}
        self.state.stage = "done"
        return {"publication_id": pid, "status": "published", "publish": self.state.publish, "metrics": self.state.metrics}

    async def _wait_until_due(self) -> None:
        """Schläft bis ``scheduled_for``; ``reschedule`` setzt den Timer neu, ``cancel`` bricht ab."""
        while not self.state.cancelled:
            target = _parse(self.state.scheduled_for)
            seen = self.state.reschedules
            if target is None:
                return
            delay = target - workflow.now()
            if delay <= timedelta(0):
                return

            def _changed(seen: int = seen) -> bool:
                return self.state.cancelled or self.state.reschedules != seen

            try:
                await workflow.wait_condition(_changed, timeout=delay)
            except TimeoutError:
                return


__all__ = ["METRIC_WINDOWS", "PublishParams", "PublishState", "PublishWorkflow"]
