"""Lösch-Workflow (Phase 4, PHASE4.md Abschnitt 7): Activity ``delete_entity(job_id)`` mit Löschnachweis.

Ein ``deletion_jobs``-Eintrag beschreibt, was gelöscht wird (``entity`` source | clip | brand_profile | workspace).
Die Activity setzt den Job auf ``running``, löscht zuerst Objektspeicher-Keys (jeder Key landet mit Zeitstempel in
``keys_deleted``; fehlende Keys zählen als bereits weg), dann Datenbankzeilen (Zähler in ``rows_deleted``), schreibt
einen Audit-Eintrag (``<entity>.deleted``, actor_type system) und schließt den Job mit ``done`` und ``finished_at``.
Fehler: Job ``failed`` mit ``error``, Audit ``<entity>.delete_failed``, Ausnahme wird weitergereicht (Temporal-Retry).

Quelle: die ``sources``-Zeile bleibt anonymisiert als Nachweis (Titel „gelöscht“, Keys leer, Status ``deleted``).
Läuft noch ein ``ClipProjectWorkflow`` (``sources.temporal_workflow_id``), wird er vorher per ``terminate`` beendet;
Fehler dabei werden nur geloggt. Storage-JSONs (``asr/``, ``diar/``, ``heatmap/``, ``candidates/``) werden über
die ``key``-Felder der ``pipeline_events``-Payloads gefunden, Render-Dateien über ``renders/<clip_id>/``.
Workspace: alle Quellen als Einzeljobs (``reason = workspace_deleted``), dann Brand-Assets, dann Audit
``workspace.deleted``; die ``workspaces``-Zeile selbst löscht die Web-App danach.

Zwei Fristen (AVV, docs/rechtliches/avv-2026-09.md): Rohmaterial ``workspaces.retention_days`` (Standard 30),
Renderings ``workspaces.render_retention_days`` (Standard 90, Migration 0006 → ``clips.delete_after``). Deshalb
verschont der reguläre Aufräumlauf (``reason = retention``) beim Löschen einer Quelle die Clips, deren eigene
Frist noch läuft: Zeile, Dateien und abhängige Zeilen bleiben, nur ``clips.candidate_id`` fällt auf NULL
(``on delete set null``). Jeder andere Grund (``user_request``, ``gdpr_request``, ``workspace_deleted``) nimmt
alle Clips mit — ein Löschverlangen darf nichts übriglassen. Wie viele Clips verschont wurden, steht als
``clips_retained`` im Löschnachweis (``deletion_jobs.rows_deleted``) und damit auch im Audit-Log.

Dazu die Retention-Activities ``find_expired(now)`` (Quellen, Clips, Workspaces) und
``enqueue_deletion(entity_id, reason, entity)``.
Keine ``pipeline_events`` aus dieser Activity (sie werden hier gelöscht). Logging nur mit IDs und Zählern.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from .. import config, db
from . import common

log = logging.getLogger("chopstr.activities.deletion")

ENTITIES = ("source", "clip", "brand_profile", "workspace")
REASONS = ("user_request", "retention", "workspace_deleted", "gdpr_request")
# Nur der reguläre Aufräumlauf verschont Clips mit eigener, noch laufender Frist. user_request,
# gdpr_request und workspace_deleted sind Löschverlangen und nehmen alle Clips der Quelle mit.
CLIP_SPARING_REASONS = ("retention",)
JSON_KEY_PREFIXES = ("asr/", "diar/", "heatmap/", "candidates/")
RENDER_PREFIX = "renders"
DELETED_TITLE = "gelöscht"
MAX_PER_RUN = 50

SQL_JOB = "select id, workspace_id, entity, entity_id, reason, requested_by, status from deletion_jobs where id = %s"
SQL_SOURCE = "select id, workspace_id, storage_key, audio_key, proxy_key, temporal_workflow_id, status from sources where id = %s"
SQL_CLIPS_OF_SOURCE = "select id, file_key, srt_key, vtt_key, poster_key, delete_after, status from clips where source_id = %s"
SQL_CLIP = "select id, source_id, file_key, srt_key, vtt_key, poster_key, status from clips where id = %s"
SQL_CAPTION_KEYS = "select ass_key, srt_key from caption_versions where clip_id = %s"
SQL_EVENT_PAYLOADS = "select payload from pipeline_events where source_id = %s and payload is not null"
SQL_ASSETS_OF_PROFILE = "select id, brand_profile_id, storage_key from brand_assets where brand_profile_id = %s"
SQL_ASSETS_OF_WORKSPACE = "select id, brand_profile_id, storage_key from brand_assets where workspace_id = %s"
# Auch schon anonymisierte Quellen, an denen noch ein Clip hängt: seit Migration 0006 überlebt ein Clip die
# Retention-Löschung seiner Quelle, und eine Workspace-Löschung darf ihn trotzdem nicht übersehen.
SQL_SOURCES_OF_WORKSPACE = (
    "select id from sources where workspace_id = %s and (status <> 'deleted' or exists ("
    "select 1 from clips c where c.source_id = sources.id and c.status <> 'deleted'"
    "))"
)
SQL_SOURCE_WORKSPACE = "select workspace_id from sources where id = %s"
SQL_CLIP_WORKSPACE = "select s.workspace_id from clips c join sources s on s.id = c.source_id where c.id = %s"
SQL_EXPIRED_SOURCES = (
    "select id from sources where delete_after < %s and status <> 'deleted' and not exists ("
    "select 1 from deletion_jobs j where j.entity = 'source' and j.entity_id = sources.id and j.status in ('queued', 'running')"
    ") order by delete_after limit %s"
)
SQL_EXPIRED_CLIPS = (
    "select id from clips where delete_after < %s and status <> 'deleted' and not exists ("
    "select 1 from deletion_jobs j where j.entity = 'clip' and j.entity_id = clips.id and j.status in ('queued', 'running')"
    ") order by delete_after limit %s"
)
SQL_EXPIRED_WORKSPACES = (
    "select id from workspaces where deletion_requested_at is not null and deletion_scheduled_for < %s and not exists ("
    "select 1 from deletion_jobs j where j.entity = 'workspace' and j.entity_id = workspaces.id and j.status in ('queued', 'running')"
    ") order by deletion_scheduled_for limit %s"
)

# Reihenfolge der DB-Löschung für eine Quelle (Fremdschlüssel von innen nach außen)
SOURCE_ROW_DELETES = (
    ("caption_versions", "delete from caption_versions where clip_id in (select id from clips where source_id = %s)"),
    ("hook_versions", "delete from hook_versions where clip_id in (select id from clips where source_id = %s)"),
    ("guest_approvals", "delete from guest_approvals where clip_id in (select id from clips where source_id = %s)"),
    ("clips", "delete from clips where source_id = %s"),
    ("candidates", "delete from candidates where source_id = %s"),
    ("transcript_corrections", "delete from transcript_corrections where source_id = %s"),
    ("transcript_versions", "delete from transcript_versions where source_id = %s"),
    ("pipeline_events", "delete from pipeline_events where source_id = %s"),
)
# Rohmaterial-Anteil einer Quelle: geht nach ``retention_days`` immer, unabhängig von den Clips.
SOURCE_ONLY_ROW_DELETES = (
    ("candidates", "delete from candidates where source_id = %s"),
    ("transcript_corrections", "delete from transcript_corrections where source_id = %s"),
    ("transcript_versions", "delete from transcript_versions where source_id = %s"),
    ("pipeline_events", "delete from pipeline_events where source_id = %s"),
)
CLIP_ROW_DELETES = (
    ("caption_versions", "delete from caption_versions where clip_id = %s"),
    ("hook_versions", "delete from hook_versions where clip_id = %s"),
    ("guest_approvals", "delete from guest_approvals where clip_id = %s"),
)
# Ein einzelner Clip samt Zeile: für die Retention-Löschung einer Quelle, die nur fällige Clips mitnimmt.
CLIP_FULL_ROW_DELETES = CLIP_ROW_DELETES + (("clips", "delete from clips where id = %s"),)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    """``timestamptz`` kommt zeitzonenbehaftet zurück; naive Werte (Tests, Altdaten) gelten als UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


# -- Temporal ------------------------------------------------------------------------------------
def terminate_workflow(workflow_id: str, s: config.Settings | None = None, reason: str = "Quelle wird gelöscht") -> bool:
    """Beendet einen laufenden Workflow per ``terminate``. Gibt False zurück, wenn er nicht (mehr) läuft."""
    s = s or config.settings()

    async def _go() -> bool:
        from temporalio.client import Client

        client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        if desc.status is not None and desc.status.name != "RUNNING":
            return False
        await handle.terminate(reason)
        return True

    return asyncio.run(_go())


def _terminate_if_running(workflow_id: str | None, s: config.Settings) -> bool:
    if not workflow_id:
        return False
    try:
        done = terminate_workflow(workflow_id, s)
    except Exception as exc:
        log.warning("workflow terminate failed workflow=%s error=%s", workflow_id, exc.__class__.__name__)
        return False
    log.info("workflow terminate workflow=%s terminated=%s", workflow_id, done)
    return done


# -- Job- und Audit-Helfer -------------------------------------------------------------------
def _load_job(ctx: common.Context, job_id: str) -> dict[str, Any]:
    row = db.fetch_one(ctx.conn, SQL_JOB, (job_id,))
    if row is None:
        raise LookupError(f"Löschauftrag {job_id} nicht gefunden")
    jid, workspace_id, entity, entity_id, reason, requested_by, status = row
    if entity not in ENTITIES:
        raise ValueError(f"Unbekannte Entität {entity!r} im Löschauftrag")
    return {
        "id": str(jid), "workspace_id": str(workspace_id), "entity": entity, "entity_id": str(entity_id),
        "reason": reason, "requested_by": str(requested_by) if requested_by else None, "status": status,
    }  # fmt: skip


def _set_job(ctx: common.Context, job_id: str, **values: Any) -> None:
    db.update(ctx.conn, "deletion_jobs", {"id": job_id}, **values)


def _audit(ctx: common.Context, job: dict, action: str, payload: dict[str, Any]) -> None:
    db.insert(
        ctx.conn,
        "audit_log",
        workspace_id=job["workspace_id"],
        actor_id=None,
        actor_type="system",
        action=action,
        entity=job["entity"],
        entity_id=job["entity_id"],
        payload=db.jsonb({"job_id": job["id"], "reason": job["reason"], "requested_by": job["requested_by"], **payload}),
    )


def _delete_keys(ctx: common.Context, keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Löscht ``(bucket, key)``-Paare; jeder Eintrag bekommt einen Nachweis mit Zeitstempel."""
    proof: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bucket, key in keys:
        if not key or (bucket, key) in seen:
            continue
        seen.add((bucket, key))
        existed = ctx.store.exists(bucket, key)
        if existed:
            ctx.store.delete(bucket, key)
        proof.append({"bucket": bucket, "key": key, "deleted_at": _now().isoformat(), "existed": existed})
        common.heartbeat("delete", key)
    return proof


def _delete_rows(ctx: common.Context, plan: tuple[tuple[str, str], ...], param: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, sql in plan:
        cur = ctx.conn.execute(sql, (param,))
        n = getattr(cur, "rowcount", -1)
        counts[table] = int(n) if n is not None and n >= 0 else 0
    return counts


def _clip_keys(ctx: common.Context, clip_id: str, file_keys: list[str | None]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = [("derived", k) for k in file_keys if k]
    for ass_key, srt_key in db.fetch_all(ctx.conn, SQL_CAPTION_KEYS, (clip_id,)):
        keys += [("derived", k) for k in (ass_key, srt_key) if k]
    keys += [("derived", k) for k in ctx.store.list("derived", f"{RENDER_PREFIX}/{clip_id}/")]
    return keys


def split_source_clips(
    ctx: common.Context, source_id: str, now: datetime, spare_live: bool
) -> tuple[list[tuple[str, list[str | None]]], list[tuple[str, list[str | None]]]]:
    """Teilt die Clips einer Quelle in ``(fällig, verschont)``; je Eintrag ``(clip_id, [file/srt/vtt/poster])``.

    ``spare_live`` ist nur beim Aufräumlauf gesetzt. Verschont wird, wessen eigene Frist noch läuft
    (``delete_after > now``); ohne Frist (NULL) und bereits gelöschte Clips gehen mit der Quelle.
    """
    due: list[tuple[str, list[str | None]]] = []
    spared: list[tuple[str, list[str | None]]] = []
    for cid, file_key, srt_key, vtt_key, poster_key, delete_after, status in db.fetch_all(ctx.conn, SQL_CLIPS_OF_SOURCE, (source_id,)):
        entry = (str(cid), [file_key, srt_key, vtt_key, poster_key])
        alive = spare_live and status != "deleted" and delete_after is not None and _aware(delete_after) > now
        (spared if alive else due).append(entry)
    return due, spared


def collect_source_keys(
    ctx: common.Context, src: dict[str, Any], clips: list[tuple[str, list[str | None]]] | None = None
) -> list[tuple[str, str]]:
    """Alle Objektspeicher-Keys einer Quelle: Original, Audio, Proxy, Clips, Captions, Pipeline-JSONs, Render-Ordner.

    ``clips`` schränkt auf die mitzulöschenden Clips ein (Aufräumlauf); ``None`` heißt: alle Clips der Quelle.
    """
    keys: list[tuple[str, str]] = []
    if src.get("storage_key"):
        keys.append(("sources", src["storage_key"]))
    keys += [("derived", k) for k in (src.get("audio_key"), src.get("proxy_key")) if k]
    if clips is None:
        clips, _ = split_source_clips(ctx, src["id"], _now(), spare_live=False)
    for clip_id, file_keys in clips:
        keys += _clip_keys(ctx, clip_id, file_keys)
    for (payload,) in db.fetch_all(ctx.conn, SQL_EVENT_PAYLOADS, (src["id"],)):
        data = _json(payload)
        key = data.get("key") if isinstance(data, dict) else None
        if isinstance(key, str) and key.startswith(JSON_KEY_PREFIXES):
            keys.append(("derived", key))
    return keys


def _delete_source_rows(ctx: common.Context, source_id: str, due_clips: list[tuple[str, list[str | None]]], spare_live: bool) -> dict[str, int]:
    """Zeilen einer Quelle löschen. Beim Aufräumlauf clipweise, damit verschonte Clips stehen bleiben."""
    if not spare_live:
        return _delete_rows(ctx, SOURCE_ROW_DELETES, source_id)
    counts: dict[str, int] = {table: 0 for table, _sql in CLIP_FULL_ROW_DELETES}
    for clip_id, _file_keys in due_clips:
        for table, n in _delete_rows(ctx, CLIP_FULL_ROW_DELETES, clip_id).items():
            counts[table] += n
    counts.update(_delete_rows(ctx, SOURCE_ONLY_ROW_DELETES, source_id))
    return counts


# -- Entitäten -----------------------------------------------------------------------------------
def _delete_source(ctx: common.Context, job: dict) -> dict[str, Any]:
    row = db.fetch_one(ctx.conn, SQL_SOURCE, (job["entity_id"],))
    if row is None:
        raise LookupError(f"Quelle {job['entity_id']} nicht gefunden")
    sid, workspace_id, storage_key, audio_key, proxy_key, workflow_id, status = row
    src = {"id": str(sid), "workspace_id": str(workspace_id), "storage_key": storage_key, "audio_key": audio_key, "proxy_key": proxy_key}
    spare_live = job["reason"] in CLIP_SPARING_REASONS
    due_clips, spared_clips = split_source_clips(ctx, src["id"], _now(), spare_live)
    terminated = _terminate_if_running(workflow_id, ctx.settings)
    keys = _delete_keys(ctx, collect_source_keys(ctx, src, due_clips))
    rows = _delete_source_rows(ctx, src["id"], due_clips, spare_live)
    rows["clips_retained"] = len(spared_clips)
    db.update(
        ctx.conn,
        "sources",
        {"id": src["id"]},
        title=DELETED_TITLE,
        original_filename=None,
        storage_key="",
        audio_key=None,
        proxy_key=None,
        sha256=None,
        brief=db.jsonb({}),
        status="deleted",
        status_message=None,
        temporal_workflow_id=None,
        deleted_at=_now(),
    )
    log.info(
        "source deleted source=%s keys=%s rows=%s clips_retained=%s terminated=%s",
        src["id"], len(keys), sum(rows.values()) - len(spared_clips), len(spared_clips), terminated,
    )  # fmt: skip
    return {"keys_deleted": keys, "rows_deleted": rows, "clips_retained": len(spared_clips), "workflow_terminated": terminated}


def _delete_clip(ctx: common.Context, job: dict) -> dict[str, Any]:
    row = db.fetch_one(ctx.conn, SQL_CLIP, (job["entity_id"],))
    if row is None:
        raise LookupError(f"Clip {job['entity_id']} nicht gefunden")
    cid, _source_id, *file_keys, _status = row
    clip_id = str(cid)
    keys = _delete_keys(ctx, _clip_keys(ctx, clip_id, list(file_keys)))
    rows = _delete_rows(ctx, CLIP_ROW_DELETES, clip_id)
    # Migration 0004 erlaubt clips.status = 'deleted'; die Zeile bleibt als Nachweis ohne Dateien
    db.update(
        ctx.conn, "clips", {"id": clip_id},
        file_key=None, srt_key=None, vtt_key=None, poster_key=None, render_plan=None,
        status="deleted", deleted_at=_now(),
    )  # fmt: skip
    log.info("clip deleted clip=%s keys=%s rows=%s", clip_id, len(keys), sum(rows.values()))
    return {"keys_deleted": keys, "rows_deleted": rows}


def _delete_assets(ctx: common.Context, sql: str, param: str, delete_sql: str) -> tuple[list[dict], int]:
    rows = db.fetch_all(ctx.conn, sql, (param,))
    keys = _delete_keys(ctx, [("derived", str(storage_key)) for _aid, _pid, storage_key in rows if storage_key])
    cur = ctx.conn.execute(delete_sql, (param,))
    n = getattr(cur, "rowcount", -1)
    return keys, int(n) if n is not None and n >= 0 else len(rows)


def _delete_brand_profile(ctx: common.Context, job: dict) -> dict[str, Any]:
    keys, n = _delete_assets(ctx, SQL_ASSETS_OF_PROFILE, job["entity_id"], "delete from brand_assets where brand_profile_id = %s")
    log.info("brand assets deleted profile=%s keys=%s rows=%s", job["entity_id"], len(keys), n)
    return {"keys_deleted": keys, "rows_deleted": {"brand_assets": n}}


def _delete_workspace(ctx: common.Context, job: dict) -> dict[str, Any]:
    wid = job["entity_id"]
    source_ids = [str(r[0]) for r in db.fetch_all(ctx.conn, SQL_SOURCES_OF_WORKSPACE, (wid,))]
    jobs: list[str] = []
    failed: list[str] = []
    for sid in source_ids:
        sub_id = enqueue(ctx, "source", sid, "workspace_deleted", workspace_id=wid, requested_by=job["requested_by"])
        jobs.append(sub_id)
        try:
            run_delete_entity(ctx, sub_id)
        except Exception as exc:
            failed.append(sub_id)
            log.warning("workspace delete: source job failed job=%s error=%s", sub_id, exc.__class__.__name__)
    keys, n = _delete_assets(ctx, SQL_ASSETS_OF_WORKSPACE, wid, "delete from brand_assets where workspace_id = %s")
    result: dict[str, Any] = {
        "keys_deleted": keys,
        "rows_deleted": {"brand_assets": n, "source_jobs": len(jobs), "source_jobs_failed": len(failed)},
        "source_jobs": jobs,
    }
    if failed:
        result["job_status"] = "failed"
        result["error"] = f"{len(failed)} von {len(jobs)} Quellen konnten nicht gelöscht werden (Jobs: {', '.join(failed)})"
    log.info("workspace deleted workspace=%s sources=%s failed=%s assets=%s", wid, len(jobs), len(failed), n)
    return result


HANDLERS = {
    "source": _delete_source,
    "clip": _delete_clip,
    "brand_profile": _delete_brand_profile,
    "workspace": _delete_workspace,
}


# -- Einstieg ----------------------------------------------------------------------------------
def run_delete_entity(ctx: common.Context, job_id: str) -> dict[str, Any]:
    """Führt einen ``deletion_jobs``-Eintrag aus. Idempotent: ein Job mit ``done`` wird nicht wiederholt."""
    job = _load_job(ctx, job_id)
    if job["status"] == "done":
        return {"job_id": job_id, "entity": job["entity"], "status": "done", "skipped": True}
    _set_job(ctx, job_id, status="running", error=None)
    try:
        result = HANDLERS[job["entity"]](ctx, job)
    except Exception as exc:
        error = f"{exc.__class__.__name__}: {str(exc)[:400]}"
        _set_job(ctx, job_id, status="failed", error=error, finished_at=_now())
        _audit(ctx, job, f"{job['entity']}.delete_failed", {"error": error})
        raise
    status = result.pop("job_status", "done")
    keys = result.get("keys_deleted", [])
    rows = result.get("rows_deleted", {})
    _set_job(
        ctx, job_id,
        status=status,
        keys_deleted=db.jsonb(keys),
        rows_deleted=db.jsonb(rows),
        error=result.get("error"),
        finished_at=_now(),
    )  # fmt: skip
    action = f"{job['entity']}.deleted" if status == "done" else f"{job['entity']}.delete_failed"
    _audit(ctx, job, action, {"keys": len(keys), "rows": rows, "error": result.get("error")})
    return {"job_id": job_id, "entity": job["entity"], "status": status, "keys": len(keys), "rows": rows, "error": result.get("error")}


def enqueue(
    ctx: common.Context,
    entity: str,
    entity_id: str,
    reason: str = "retention",
    workspace_id: str | None = None,
    requested_by: str | None = None,
) -> str:
    """Legt einen ``deletion_jobs``-Eintrag (``queued``) an und gibt seine ID zurück."""
    if entity not in ENTITIES:
        raise ValueError(f"Unbekannte Entität {entity!r}")
    if reason not in REASONS:
        raise ValueError(f"Unbekannter Löschgrund {reason!r}")
    if workspace_id is None:
        if entity == "workspace":
            workspace_id = entity_id
        elif entity == "source":
            row = db.fetch_one(ctx.conn, SQL_SOURCE_WORKSPACE, (entity_id,))
            if row is None:
                raise LookupError(f"Quelle {entity_id} nicht gefunden")
            workspace_id = str(row[0])
        elif entity == "clip":
            row = db.fetch_one(ctx.conn, SQL_CLIP_WORKSPACE, (entity_id,))
            if row is None:
                raise LookupError(f"Clip {entity_id} nicht gefunden")
            workspace_id = str(row[0])
        else:
            raise ValueError("workspace_id fehlt")
    inserted = db.insert(
        ctx.conn,
        "deletion_jobs",
        returning="id",
        workspace_id=workspace_id,
        entity=entity,
        entity_id=entity_id,
        reason=reason,
        requested_by=requested_by,
        status="queued",
    )
    return str(inserted[0])


def run_find_expired(ctx: common.Context, now: datetime, limit: int = MAX_PER_RUN) -> dict[str, list[str]]:
    """Fällige Quellen, fällige Clips (eigene Frist, Migration 0006) und Workspaces nach der Karenz — je ohne offenen Job."""
    sources = [str(r[0]) for r in db.fetch_all(ctx.conn, SQL_EXPIRED_SOURCES, (now, limit))]
    clips = [str(r[0]) for r in db.fetch_all(ctx.conn, SQL_EXPIRED_CLIPS, (now, limit))]
    workspaces = [str(r[0]) for r in db.fetch_all(ctx.conn, SQL_EXPIRED_WORKSPACES, (now, limit))]
    log.info("retention scan sources=%s clips=%s workspaces=%s", len(sources), len(clips), len(workspaces))
    return {"sources": sources, "clips": clips, "workspaces": workspaces}


def _parse_now(value: str | datetime | None) -> datetime:
    if value is None:
        return _now()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@activity.defn(name="delete_entity")
def delete_entity(job_id: str) -> dict:
    ctx = common.open_context()
    try:
        return run_delete_entity(ctx, job_id)
    finally:
        ctx.close()


@activity.defn(name="find_expired")
def find_expired(now: str | None = None, limit: int = MAX_PER_RUN) -> dict:
    ctx = common.open_context()
    try:
        return run_find_expired(ctx, _parse_now(now), limit)
    finally:
        ctx.close()


@activity.defn(name="enqueue_deletion")
def enqueue_deletion(entity_id: str, reason: str = "retention", entity: str = "source") -> str:
    ctx = common.open_context()
    try:
        return enqueue(ctx, entity, entity_id, reason)
    finally:
        ctx.close()


__all__ = [
    "CLIP_SPARING_REASONS",
    "ENTITIES",
    "MAX_PER_RUN",
    "REASONS",
    "collect_source_keys",
    "delete_entity",
    "enqueue",
    "enqueue_deletion",
    "find_expired",
    "run_delete_entity",
    "run_find_expired",
    "split_source_clips",
    "terminate_workflow",
]
