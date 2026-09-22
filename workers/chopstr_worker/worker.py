"""Worker-Einstieg: ``python -m chopstr_worker.worker --queues cpu,gpu``.

Startet pro Queue einen Temporal-Worker im selben Prozess. Der CPU-Worker registriert den Workflow
und die CPU-Activities, der GPU-Worker die ASR/Diarisierungs-Activities. In der lokalen Entwicklung
darf ein CPU-Rechner beide Queues bedienen (dann laufen ASR-Modelle auf der CPU, langsam).
Logging enthält nur IDs, Dauern und Zähler, keine Transkriptinhalte.
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
from .workflows import ClipProjectWorkflow

log = logging.getLogger("chopstr.worker")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="chopstr Temporal-Worker")
    ap.add_argument("--queues", default="cpu", help="Kommagetrennt: cpu, gpu (Default: cpu)")
    ap.add_argument("--max-concurrent", type=int, default=2, help="Parallele Activities pro Worker")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


async def run_workers(queues: list[str], max_concurrent: int = 2) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    s = config.settings()
    residency.assert_eu_host(f"//{s.temporal_address}", s)
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    workers = []
    executor = ThreadPoolExecutor(max_workers=max(2, max_concurrent * len(queues)))
    for q in queues:
        if q == "cpu":
            workers.append(
                Worker(
                    client,
                    task_queue=s.task_queue_cpu,
                    workflows=[ClipProjectWorkflow],
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
    asyncio.run(run_workers(queues, args.max_concurrent))


if __name__ == "__main__":
    main()
