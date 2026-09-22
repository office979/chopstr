"""Pipeline-Ereignisse (Tabelle ``pipeline_events``) und Statuswechsel in ``sources``.

Die UI liest ``pipeline_events`` per Polling/SSE. Meldungen sind deutsch, ohne Gedankenstriche,
ohne Transkriptinhalte (nur IDs, Dauern, Zähler).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any

from . import db

log = logging.getLogger("chopstr.events")

STATUSES = ("started", "progress", "finished", "failed", "skipped")
SOURCE_STATUSES = (
    "uploading", "uploaded", "ingesting", "transcribing", "analyzing", "scoring", "ready", "failed", "deleted",
)  # fmt: skip


def emit(
    conn: db.Connection,
    source_id: str,
    step: str,
    status: str,
    message: str | None = None,
    progress: float | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Schreibt eine Zeile in ``pipeline_events``."""
    if status not in STATUSES:
        raise ValueError(f"Ungültiger Event-Status: {status}")
    if progress is not None:
        progress = max(0.0, min(1.0, float(progress)))
    conn.execute(
        "insert into pipeline_events (source_id, step, status, progress, message, payload) "
        "values (%s, %s, %s, %s, %s, %s)",
        (source_id, step, status, progress, message, db.jsonb(payload) if payload is not None else None),
    )
    log.info("event source=%s step=%s status=%s progress=%s", source_id, step, status, progress)


def set_source_status(conn: db.Connection, source_id: str, status: str, message: str | None = None) -> None:
    """Statuswechsel in ``sources`` (mit optionaler ``status_message``)."""
    if status not in SOURCE_STATUSES:
        raise ValueError(f"Ungültiger Quellstatus: {status}")
    db.update(conn, "sources", {"id": source_id}, status=status, status_message=message)


def failure_message(step: str, exc: BaseException) -> str:
    """Deutsche, verständliche Fehlermeldung ohne Transkriptinhalte."""
    prefix = {
        "probe_and_extract": "Audio konnte nicht extrahiert werden",
        "transcribe_de": "Transkription fehlgeschlagen",
        "diarize": "Sprechererkennung fehlgeschlagen",
        "heatmap": "Heatmap konnte nicht berechnet werden",
        "fuse_and_nlp": "Zusammenführung von Transkript und Sprechern fehlgeschlagen",
        "detect_candidates": "Kandidatensuche fehlgeschlagen",
        "render": "Rendern fehlgeschlagen",
    }.get(step, f"Schritt {step} fehlgeschlagen")
    detail = str(exc).strip() or exc.__class__.__name__
    if len(detail) > 300:
        detail = detail[:297] + "..."
    return f"{prefix}: {detail}"


@contextmanager
def step(
    conn: db.Connection,
    source_id: str,
    name: str,
    start_message: str | None = None,
    fail_status: str | None = "failed",
):
    """Kontextmanager: ``started`` beim Eintritt, ``finished`` beim Verlassen, ``failed`` bei Ausnahme.

    Im Body kann ``ctx.finish(message=..., payload=...)`` die Abschlussmeldung setzen und
    ``ctx.progress(fraction, message)`` Zwischenstände melden. Bei einer Ausnahme wird zusätzlich
    ``sources.status`` auf ``fail_status`` gesetzt (falls nicht None) und die Ausnahme weitergereicht.
    """
    ctx = StepContext(conn, source_id, name)
    emit(conn, source_id, name, "started", start_message)
    try:
        yield ctx
    except BaseException as exc:
        msg = failure_message(name, exc)
        emit(conn, source_id, name, "failed", msg, payload={"error_type": exc.__class__.__name__})
        if fail_status:
            set_source_status(conn, source_id, fail_status, msg)
        raise
    else:
        payload = dict(ctx.payload)
        payload.setdefault("duration_s", round(time.monotonic() - ctx.t0, 3))
        emit(conn, source_id, name, "finished", ctx.message, progress=1.0, payload=payload)


class StepContext:
    def __init__(self, conn: db.Connection, source_id: str, name: str):
        self.conn, self.source_id, self.name = conn, source_id, name
        self.t0 = time.monotonic()
        self.message: str | None = None
        self.payload: dict[str, Any] = {}

    def progress(self, fraction: float, message: str | None = None, **payload: Any) -> None:
        emit(self.conn, self.source_id, self.name, "progress", message, progress=fraction, payload=payload or None)

    def finish(self, message: str | None = None, **payload: Any) -> None:
        self.message = message
        self.payload.update(payload)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.t0


__all__ = ["SOURCE_STATUSES", "STATUSES", "StepContext", "emit", "failure_message", "set_source_status", "step"]
