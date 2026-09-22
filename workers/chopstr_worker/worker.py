"""Worker-Einstieg: ``python -m chopstr_worker.worker --queues cpu,gpu [--ensure-schedules]``.

Startet pro Queue einen Temporal-Worker im selben Prozess. Der CPU-Worker registriert die Workflows
(``ClipProjectWorkflow``, ``DeletionWorkflow``, ``RetentionWorkflow``, ``OutboxWorkflow``, ``PublishWorkflow``,
``LearningWorkflow``, ``WeeklyReportWorkflow``) und die CPU-Activities, der GPU-Worker die
ASR/Diarisierungs-Activities. In der lokalen Entwicklung darf ein CPU-Rechner beide Queues bedienen
(dann laufen ASR-Modelle auf der CPU, langsam). ``--ensure-schedules`` legt die Temporal-Schedules
``retention-daily`` (Cron ``RETENTION_CRON``), ``outbox-dispatch`` (alle ``OUTBOX_INTERVAL_S`` Sekunden),
``learning-nightly`` (Cron ``LEARNING_CRON``) und ``weekly-report`` (Cron ``WEEKLY_REPORT_CRON``) an,
Zeitzone ``RETENTION_TIMEZONE``, idempotent. Logging enthält nur IDs, Dauern und Zähler, keine Transkriptinhalte.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
from concurrent.futures import ThreadPoolExecutor

from . import config, residency
from .activities import CPU_ACTIVITIES, GPU_ACTIVITIES
from .workflows import (
    ClipProjectWorkflow,
    DeletionWorkflow,
    LearningWorkflow,
    OutboxWorkflow,
    PublishWorkflow,
    RetentionWorkflow,
    WeeklyReportWorkflow,
)
from .workflows import learning as learning_wf
from .workflows import outbox as outbox_wf
from .workflows import reports as reports_wf
from .workflows import retention as retention_wf

WORKFLOWS = [
    ClipProjectWorkflow, DeletionWorkflow, RetentionWorkflow,
    OutboxWorkflow, PublishWorkflow, LearningWorkflow, WeeklyReportWorkflow,
]  # fmt: skip

log = logging.getLogger("chopstr.worker")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="chopstr Temporal-Worker")
    ap.add_argument("--queues", default="cpu", help="Kommagetrennt: cpu, gpu (Default: cpu)")
    ap.add_argument("--max-concurrent", type=int, default=2, help="Parallele Activities pro Worker")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument(
        "--ensure-schedules",
        action="store_true",
        help="Temporal-Schedules anlegen, falls sie fehlen (retention-daily, outbox-dispatch, learning-nightly, weekly-report)",
    )
    return ap.parse_args(argv)


def schedule_specs(s: config.Settings | None = None) -> list[tuple[str, str, object, object]]:
    """``(schedule_id, workflow_id, run_fn, params)`` für alle Schedules des Workers; Spec je ID in ``_spec``."""
    s = s or config.settings()
    q = s.task_queue_cpu
    return [
        (retention_wf.SCHEDULE_ID, retention_wf.WORKFLOW_ID, RetentionWorkflow.run, retention_wf.RetentionParams(task_queue=q)),
        (outbox_wf.SCHEDULE_ID, outbox_wf.WORKFLOW_ID, OutboxWorkflow.run, outbox_wf.OutboxParams(task_queue=q)),
        (learning_wf.SCHEDULE_ID, learning_wf.WORKFLOW_ID, LearningWorkflow.run, learning_wf.LearningParams(task_queue=q)),
        (reports_wf.SCHEDULE_ID, reports_wf.WORKFLOW_ID, WeeklyReportWorkflow.run, reports_wf.WeeklyReportParams(task_queue=q)),
    ]


def _spec(schedule_id: str, s: config.Settings):
    from datetime import timedelta

    from temporalio.client import ScheduleIntervalSpec, ScheduleSpec

    tz = s.retention_timezone
    if schedule_id == outbox_wf.SCHEDULE_ID:
        every = timedelta(seconds=max(5, int(s.outbox_interval_s)))
        return ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)], time_zone_name=tz)
    cron = {
        retention_wf.SCHEDULE_ID: s.retention_cron,
        learning_wf.SCHEDULE_ID: s.learning_cron,
        reports_wf.SCHEDULE_ID: s.weekly_report_cron,
    }[schedule_id]
    return ScheduleSpec(cron_expressions=[cron], time_zone_name=tz)


async def ensure_schedules(client, s: config.Settings | None = None) -> dict[str, str]:
    """Legt alle Schedules an (``retention-daily``, ``outbox-dispatch``, ``learning-nightly``, ``weekly-report``).
    Existiert einer schon, wird er übersprungen (idempotent). Ergebnis je ID ``created`` oder ``exists``."""
    from temporalio.client import (
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleAlreadyRunningError,
        ScheduleOverlapPolicy,
        SchedulePolicy,
    )

    s = s or config.settings()
    out: dict[str, str] = {}
    for schedule_id, workflow_id, run_fn, params in schedule_specs(s):
        schedule = Schedule(
            action=ScheduleActionStartWorkflow(run_fn, params, id=workflow_id, task_queue=s.task_queue_cpu),
            spec=_spec(schedule_id, s),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),  # kein zweiter Lauf, solange einer läuft
        )
        try:
            await client.create_schedule(schedule_id, schedule)
        except ScheduleAlreadyRunningError:
            log.info("schedule exists id=%s", schedule_id)
            out[schedule_id] = "exists"
            continue
        log.info("schedule created id=%s tz=%s", schedule_id, s.retention_timezone)
        out[schedule_id] = "created"
    return out


async def run_workers(queues: list[str], max_concurrent: int = 2, schedules: bool = False) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    s = config.settings()
    residency.assert_eu_host(f"//{s.temporal_address}", s)
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    if schedules:
        await ensure_schedules(client, s)
    workers = []
    executor = ThreadPoolExecutor(max_workers=max(2, max_concurrent * len(queues)))
    for q in queues:
        if q == "cpu":
            workers.append(
                Worker(
                    client,
                    task_queue=s.task_queue_cpu,
                    workflows=WORKFLOWS,
                    activities=CPU_ACTIVITIES,
                    activity_executor=executor,
                    max_concurrent_activities=max_concurrent,
                )
            )
        elif q == "gpu":
            workers.append(
                Worker(
                    client,
                    task_queue=s.task_queue_gpu,
                    activities=GPU_ACTIVITIES,
                    activity_executor=executor,
                    max_concurrent_activities=1,  # ein Modell pro GPU
                )
            )
        else:
            raise SystemExit(f"Unbekannte Queue {q!r} (erlaubt: cpu, gpu)")
    log.info("worker start queues=%s temporal=%s namespace=%s", queues, s.temporal_address, s.temporal_namespace)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # pragma: no cover
            loop.add_signal_handler(sig, stop.set)

    async with _all(workers):
        await stop.wait()
    executor.shutdown(wait=False)
    log.info("worker stop")


class _all:
    """Mehrere Worker als ein Kontextmanager."""

    def __init__(self, workers):
        self.workers = workers

    async def __aenter__(self):
        for w in self.workers:
            await w.__aenter__()
        return self

    async def __aexit__(self, *exc):
        for w in reversed(self.workers):
            await w.__aexit__(*exc)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    queues = [q.strip() for q in args.queues.split(",") if q.strip()]
    asyncio.run(run_workers(queues, args.max_concurrent, schedules=args.ensure_schedules))


if __name__ == "__main__":
    main()
