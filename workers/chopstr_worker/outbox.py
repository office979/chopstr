"""Outbox (Phase 5a): Statuswechsel als Ereignisse in ``outbox_events``, Quelle für Webhooks.

Web und Worker schreiben hier bei jedem relevanten Statuswechsel eine Zeile; der ``OutboxWorkflow`` verteilt
sie an die aktiven ``webhook_endpoints`` (siehe ``activities/webhooks.py``). Payloads enthalten nur IDs,
Titel, Status, Zähler und URLs, nie Transkriptinhalte oder Hook-Texte.

Hooks aus ``events.py``: ``on_source_status`` (``source.ready``, ``source.failed``) und die Schrittfunktionen
``on_step_finished`` / ``on_step_failed`` für den Render-Schritt (``clip.rendered``, ``clip.failed``). Damit
erreicht ``activities/render.py`` die Outbox über ``events.step`` ohne eigene Aufrufe.
"""

from __future__ import annotations

import logging
from typing import Any

from . import db

log = logging.getLogger("chopstr.outbox")

EVENTS = (
    "source.ready",
    "source.failed",
    "candidates.ready",
    "clip.rendered",
    "clip.failed",
    "guest_approval.decided",
    "publication.published",
    "publication.failed",
    "usage.threshold",
)

SQL_SOURCE_META = "select workspace_id, title, status_message from sources where id = %s"
SQL_CLIP_META = (
    "select c.source_id, c.platform, c.duration_s, c.render_error, s.workspace_id, s.title "
    "from clips c join sources s on s.id = c.source_id where c.id = %s"
)


def emit(
    conn: db.Connection,
    workspace_id: str,
    event: str,
    entity: str | None,
    entity_id: str | None,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Schreibt eine ``outbox_events``-Zeile und gibt ihre ID zurück."""
    if event not in EVENTS:
        raise ValueError(f"Unbekanntes Outbox-Ereignis: {event}")
    row = db.insert(
        conn,
        "outbox_events",
        returning="id",
        workspace_id=workspace_id,
        event=event,
        entity=entity,
        entity_id=entity_id,
        payload=db.jsonb(dict(payload or {})),
    )
    log.info("outbox event=%s entity=%s id=%s", event, entity, entity_id)
    return int(row[0]) if row else None


# -- Hooks aus events.py --------------------------------------------------------------------------
def on_source_status(conn: db.Connection, source_id: str, status: str, message: str | None) -> None:
    """``sources.status`` wurde auf ``ready`` oder ``failed`` gesetzt."""
    if status not in ("ready", "failed"):
        return
    row = db.fetch_one(conn, SQL_SOURCE_META, (source_id,))
    if row is None:
        return
    workspace_id, title, _prev = row
    payload: dict[str, Any] = {"source_id": str(source_id), "status": status, "title": title}
    if status == "failed":
        payload["error"] = message
    emit(conn, str(workspace_id), f"source.{status}", "source", str(source_id), payload)


def clip_event(conn: db.Connection, clip_id: str, status: str, error: str | None = None) -> None:
    """``clip.rendered`` oder ``clip.failed`` für einen Clip (Metadaten aus ``clips`` und ``sources``)."""
    row = db.fetch_one(conn, SQL_CLIP_META, (clip_id,))
    if row is None:
        return
    source_id, platform, duration_s, render_error, workspace_id, title = row
    payload: dict[str, Any] = {
        "clip_id": str(clip_id),
        "source_id": str(source_id),
        "platform": platform,
        "status": status,
        "title": title,
    }
    if status == "rendered":
        payload["duration_s"] = float(duration_s) if duration_s is not None else None
    else:
        payload["error"] = error or render_error
    emit(conn, str(workspace_id), f"clip.{status}", "clip", str(clip_id), payload)


def on_step_finished(conn: db.Connection, source_id: str, step: str, payload: dict[str, Any]) -> None:
    if step == "render" and payload.get("clip_id"):
        clip_event(conn, str(payload["clip_id"]), "rendered")


def on_step_failed(conn: db.Connection, source_id: str, step: str, context: dict[str, Any], message: str) -> None:
    if step == "render" and context.get("clip_id"):
        clip_event(conn, str(context["clip_id"]), "failed", message)


def candidates_ready(conn: db.Connection, workspace_id: str, source_id: str, candidates: int, gate_passed: int) -> None:
    emit(
        conn, workspace_id, "candidates.ready", "source", source_id,
        {"source_id": source_id, "candidates": int(candidates), "gate_passed": int(gate_passed)},
    )  # fmt: skip


def publication_event(conn: db.Connection, workspace_id: str, publication: dict[str, Any], status: str) -> None:
    """``publication.published`` oder ``publication.failed``."""
    payload: dict[str, Any] = {
        "publication_id": str(publication["id"]),
        "clip_id": str(publication.get("clip_id") or ""),
        "platform": publication.get("platform"),
        "status": status,
    }
    if status == "published":
        payload["external_id"] = publication.get("external_id")
        payload["external_url"] = publication.get("external_url")
        payload["published_at"] = publication.get("published_at")
    else:
        payload["error"] = publication.get("error")
    emit(conn, workspace_id, f"publication.{status}", "publication", str(publication["id"]), payload)


__all__ = [
    "EVENTS",
    "candidates_ready",
    "clip_event",
    "emit",
    "on_source_status",
    "on_step_failed",
    "on_step_finished",
    "publication_event",
]
