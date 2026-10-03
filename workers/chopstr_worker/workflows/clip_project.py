"""ClipProjectWorkflow: ein Longform-Asset von Ingest bis Freigabe und Render.

  probe_and_extract (cpu)
    -> gather(transcribe_de (gpu), diarize (gpu), heatmap (cpu))
    -> fuse_and_nlp (cpu)
    -> detect_candidates (cpu, Story-Engine mit LLM, Heartbeat-Timeout 15 Minuten, Heartbeat pro Kapitel)
    -> notify(candidates_ready)
    -> Warten auf Freigabe-Signale (approve / finish_review), bis zu 14 Tage
    -> render_pack (cpu, Phase 3, Stub)

Retry-Policies wie im Gerüst: IO_RETRY (5 Versuche), LLM_RETRY (3 Versuche);
``ResidencyError``, ``SchemaError`` und ``TranscribeError`` sind nicht wiederholbar.
Der Workflow-Code ist deterministisch: keine Umgebungsvariablen, keine I/O; Queues kommen als Parameter.

Die Zeitgrenzen der Stufen richten sich nach der Laenge der Quelle (``zeitgrenze``), nicht nach
Festwerten. Die Laenge kommt aus dem Ergebnis von ``probe_and_extract`` und liegt damit im
Event-Log, ein Replay rechnet also dieselben Werte. Untergrenzen sind die frueheren Festwerte,
kurze Quellen verhalten sich unveraendert.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

NON_RETRYABLE = ["ResidencyError", "SchemaError", "TranscribeError", "NotImplementedError", "LookupError"]

IO_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=5), non_retryable_error_types=NON_RETRYABLE)
GPU_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30), non_retryable_error_types=NON_RETRYABLE)
LLM_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10), non_retryable_error_types=NON_RETRYABLE)

REVIEW_TIMEOUT = timedelta(days=14)

# Zeitgrenzen je Stufe: (Untergrenze in Minuten, Faktor auf die Laenge der Quelle).
#
# Vorher waren das Festwerte. Sie stammten aus einer Zeit, in der das Upload-Limit bei 5 GB lag,
# also rund eineinhalb Stunden 1080p. Mit 25 GB sind sieben Stunden moeglich, und dann reisst
# nicht die Dateigroesse, sondern die Transkription: zwei Stunden Grenze fuer sieben Stunden Ton.
#
# Die Untergrenzen sind exakt die bisherigen Festwerte. Kurze Quellen verhalten sich damit
# unveraendert, nur lange bekommen mehr Zeit. Die Faktoren sind bewusst grosszuegig, weil ein zu
# knapper Timeout einen fertig gerechneten Lauf wegwirft, waehrend ein zu weiter nur einen
# haengenden Job spaeter abbricht. Gegen echtes Haengen schuetzen die Heartbeat-Timeouts, nicht
# diese Grenzen.
ZEITGRENZEN: dict[str, tuple[int, float]] = {
    "ingest": (60, 0.5),   # Audio extrahieren und Proxy bauen, I/O-lastig
    "asr": (120, 1.0),     # Transkription und Diarisierung, laufen parallel auf der GPU
    "nlp": (30, 0.3),      # Zusammenfuehren und deutsche Sprachanalyse
    "detect": (60, 0.75),  # Story-Engine, ein LLM-Aufruf je Kapitel und Kandidat
}
# Notbremse: keine Stufe darf laenger laufen als das, egal wie lang die Quelle ist.
ZEITGRENZE_MAX_MIN = 12 * 60


def zeitgrenze(stufe: str, dauer_s: float, untergrenze_min: int | None = None) -> timedelta:
    """Zeitgrenze einer Stufe aus der Laenge der Quelle.

    Rein und deterministisch, damit der Workflow bei einem Replay dieselben Werte erhaelt.
    ``untergrenze_min`` uebersteuert die Untergrenze aus der Tabelle (fuer die Parameter des
    Workflows, die von aussen gesetzt werden koennen).
    """
    basis, faktor = ZEITGRENZEN[stufe]
    unten = basis if untergrenze_min is None else untergrenze_min
    aus_dauer = (max(0.0, dauer_s) / 60.0) * faktor
    return timedelta(minutes=min(ZEITGRENZE_MAX_MIN, max(unten, round(aus_dauer))))


@dataclass
class ClipProjectParams:
    source_id: str
    workspace_id: str = ""
    cpu_queue: str = "chopstr-cpu"
    gpu_queue: str = "chopstr-gpu"
    ingest_timeout_min: int = 60
    asr_timeout_min: int = 120
    review_days: int = 14


@dataclass
class ClipProjectState:
    approved: list[tuple[str, str]] = field(default_factory=list)
    rendered: list[str] = field(default_factory=list)
    review_finished: bool = False
    stage: str = "queued"


@workflow.defn(name="ClipProjectWorkflow")
class ClipProjectWorkflow:
    def __init__(self) -> None:
        self.state = ClipProjectState()

    # -- Signale und Queries -------------------------------------------------------------------
    @workflow.signal
    def approve(self, candidate_id: str, destination: str) -> None:
        self.state.approved.append((candidate_id, destination))

    @workflow.signal
    def finish_review(self) -> None:
        self.state.review_finished = True

    @workflow.query
    def stage(self) -> str:
        return self.state.stage

    @workflow.query
    def rendered(self) -> list[str]:
        return list(self.state.rendered)

    # -- Ablauf --------------------------------------------------------------------------------
    @workflow.run
    async def run(self, params: ClipProjectParams) -> list[str]:
        sid = params.source_id
        cpu = dict(task_queue=params.cpu_queue, retry_policy=IO_RETRY, heartbeat_timeout=timedelta(minutes=5))
        gpu = dict(task_queue=params.gpu_queue, retry_policy=GPU_RETRY, heartbeat_timeout=timedelta(minutes=10))
        # Fuer die erste Stufe ist die Laenge der Quelle noch unbekannt; hier gilt der Parameter.
        # Alle spaeteren Stufen rechnen mit `zeitgrenze` aus der gemessenen Dauer.
        ingest_t = timedelta(minutes=params.ingest_timeout_min)

        self.state.stage = "ingesting"
        # Das Ergebnis traegt die Laenge der Quelle. Vorher wurde es verworfen, und alle
        # folgenden Stufen liefen gegen Festwerte.
        info = await workflow.execute_activity("probe_and_extract", sid, start_to_close_timeout=ingest_t, **cpu)
        dauer_s = float((info or {}).get("duration_s") or 0.0)

        self.state.stage = "transcribing"
        asr_dyn = zeitgrenze("asr", dauer_s, params.asr_timeout_min)
        ingest_dyn = zeitgrenze("ingest", dauer_s, params.ingest_timeout_min)
        await asyncio.gather(
            workflow.execute_activity("transcribe_de", sid, start_to_close_timeout=asr_dyn, **gpu),
            workflow.execute_activity("diarize", sid, start_to_close_timeout=asr_dyn, **gpu),
            workflow.execute_activity("heatmap", sid, start_to_close_timeout=ingest_dyn, **cpu),
        )

        self.state.stage = "analyzing"
        await workflow.execute_activity(
            "fuse_and_nlp", sid, start_to_close_timeout=zeitgrenze("nlp", dauer_s), **cpu
        )

        self.state.stage = "scoring"
        await workflow.execute_activity(
            "detect_candidates",
            sid,
            task_queue=params.cpu_queue,
            start_to_close_timeout=zeitgrenze("detect", dauer_s),
            heartbeat_timeout=timedelta(minutes=15),  # ein Heartbeat pro Kapitel
            retry_policy=LLM_RETRY,
        )
        await workflow.execute_activity("notify", args=[sid, "candidates_ready"], start_to_close_timeout=timedelta(minutes=5), **cpu)

        # Mensch entscheidet. Workflow schläft bis zu 14 Tage. Freigaben, die vor finish_review
        # eintreffen, werden noch gerendert.
        self.state.stage = "review"
        done = 0
        review_timeout = timedelta(days=params.review_days)
        while True:
            seen = done

            def _has_work(seen: int = seen) -> bool:
                return len(self.state.approved) > seen or self.state.review_finished

            try:
                await workflow.wait_condition(_has_work, timeout=review_timeout)
            except TimeoutError:
                break
            batch = self.state.approved[done:]
            done = len(self.state.approved)
            if batch:
                self.state.stage = "rendering"
                outs = await asyncio.gather(
                    *[
                        workflow.execute_activity(
                            "render_pack", args=[cid, dest], start_to_close_timeout=timedelta(minutes=40), **cpu
                        )
                        for cid, dest in batch
                    ]
                )
                self.state.rendered.extend(outs)
                await workflow.execute_activity(
                    "notify", args=[sid, "renders_ready"], start_to_close_timeout=timedelta(minutes=5), **cpu
                )
                self.state.stage = "review"
            if self.state.review_finished and done >= len(self.state.approved):
                break
        self.state.stage = "done"
        return list(self.state.rendered)


__all__ = ["GPU_RETRY", "IO_RETRY", "LLM_RETRY", "NON_RETRYABLE", "REVIEW_TIMEOUT", "ClipProjectParams", "ClipProjectState", "ClipProjectWorkflow"]
