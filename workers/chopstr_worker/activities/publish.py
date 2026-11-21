"""Publishing (Phase 5b): ``load_publication``, ``publish_clip``, ``fetch_metrics``, ``cancel_publication``.

Der Worker besitzt Zeitplanung und Metrik-Fenster; das eigentliche Posten macht die Web-App über
``/api/internal/publish`` (Provider-SDKs, OAuth). Gates vor dem Publish: Clip ``rendered`` (oder ``exported``),
Kandidat ``accepted``, Gast-Freigabe ``approved`` falls der Clip sie verlangt. Ergebnis in ``publications``
(``status``, ``external_id``, ``external_url``, ``published_at``, ``error``), Outbox ``publication.published``
oder ``publication.failed``, Decision Log ``publish``.

``fetch_metrics(publication_id, window)`` holt ``/api/internal/metrics`` und schreibt ``performance_feedback``
mit Reward (Master These 1): ``follows_per_1k``, ``saves_per_1k``, ``account_median_views`` (Median der
``views`` der letzten 20 7d-Zeilen desselben Accounts), ``outlier_score`` (views / Median) und
``reward = 0,5 * follows_norm + 0,3 * saves_norm + 0,2 * outlier_norm``; jede Kennzahl wird durch den
Account-Median derselben Kennzahl geteilt und auf 3 gedeckelt. Fehlende Metriken bleiben ``null`` und der
Reward wird nur aus den vorhandenen Anteilen gebildet (Gewichte neu normiert).
Kein Autopublishing: jede Publikation entsteht in der Web-App aus einer Nutzeraktion oder einem API-Aufruf.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import activity

from .. import db, decision_log, internal_api, outbox
from . import common

log = logging.getLogger("chopstr.activities.publish")

PUBLISHABLE_CLIP_STATUSES = ("rendered", "exported")
PUBLISHABLE_STATUSES = ("scheduled", "publishing", "failed")
METRIC_WINDOWS = internal_api.METRIC_WINDOWS
REWARD_WEIGHTS = {"follows": 0.5, "saves": 0.3, "outlier": 0.2}
NORM_CAP = 3.0
HISTORY_LIMIT = 20

SQL_PUBLICATION = (
    "select p.id, coalesce(p.workspace_id, s.workspace_id), p.clip_id, p.connection_id, p.platform, p.status, "
    "p.scheduled_for, p.external_id, p.external_url, p.published_at, p.metrics, p.error, "
    "c.status, c.candidate_id, c.guest_approval_required, c.source_id, s.brand_profile_id "
    "from publications p join clips c on c.id = p.clip_id join sources s on s.id = c.source_id where p.id = %s"
)
SQL_VERDICT = "select human_verdict from candidates where id = %s"
# Urteil im Sperrgrund, gleichlautend mit der Web-App (verdictReason in apps/web/lib/publishing/gates.ts).
VERDICT_LABELS: dict[str | None, str] = {None: "offen", "rejected": "abgelehnt", "edited": "durch eine neue Version ersetzt"}
SQL_GUEST = "select decision from guest_approvals where clip_id = %s order by created_at desc limit 1"
SQL_FEEDBACK_ID = "select id from performance_feedback where publication_id = %s and metric_window = %s"
SQL_ACCOUNT_HISTORY = (
    "select f.views, f.follows_per_1k, f.saves_per_1k from performance_feedback f "
    "join publications p on p.id = f.publication_id "
    "where f.workspace_id = %s and f.platform = %s and coalesce(p.connection_id::text, '') = %s "
    "and f.metric_window = '7d' and f.publication_id <> %s order by f.fetched_at desc limit %s"
)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return str(value)


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


# -- Laden und Gates -----------------------------------------------------------------------------
def load_publication(ctx: common.Context, publication_id: str) -> dict[str, Any]:
    """Publikation plus Clip- und Quellenkontext (Zeitstempel als ISO-Strings, Workflow-tauglich)."""
    row = db.fetch_one(ctx.conn, SQL_PUBLICATION, (publication_id,))
    if row is None:
        raise LookupError(f"Publikation {publication_id} nicht gefunden")
    keys = [
        "id", "workspace_id", "clip_id", "connection_id", "platform", "status", "scheduled_for", "external_id",
        "external_url", "published_at", "metrics", "error", "clip_status", "candidate_id",
        "guest_approval_required", "source_id", "brand_profile_id",
    ]  # fmt: skip
    out = dict(zip(keys, row))
    for k in ("id", "workspace_id", "clip_id", "connection_id", "candidate_id", "source_id", "brand_profile_id"):
        out[k] = str(out[k]) if out.get(k) else None
    out["scheduled_for"] = _iso(out.get("scheduled_for"))
    out["published_at"] = _iso(out.get("published_at"))
    out["metrics"] = dict(_json(out.get("metrics"), {}) or {})
    out["guest_approval_required"] = bool(out.get("guest_approval_required"))
    return out


def check_gates(ctx: common.Context, pub: dict[str, Any]) -> list[str]:
    """Deutsche Gründe, warum nicht veröffentlicht werden darf; leer, wenn alle Gates offen sind."""
    reasons = []
    if pub.get("clip_status") not in PUBLISHABLE_CLIP_STATUSES:
        reasons.append(f"Clip ist nicht gerendert (Status {pub.get('clip_status') or 'unbekannt'})")
    if pub.get("candidate_id"):
        row = db.fetch_one(ctx.conn, SQL_VERDICT, (pub["candidate_id"],))
        verdict = row[0] if row else None
        if verdict != "accepted":
            reasons.append(f"Kandidat ist nicht angenommen (Urteil {VERDICT_LABELS.get(verdict, str(verdict))})")
    else:
        reasons.append("Clip hat keinen Kandidaten")
    if pub.get("guest_approval_required"):
        row = db.fetch_one(ctx.conn, SQL_GUEST, (pub["clip_id"],))
        decision = row[0] if row else None
        if decision != "approved":
            reasons.append(f"Gast-Freigabe fehlt (Entscheidung {decision or 'offen'})")
    return reasons


def _set(ctx: common.Context, publication_id: str, **values: Any) -> None:
    db.update(ctx.conn, "publications", {"id": publication_id}, **values)


def _log_publish(ctx: common.Context, pub: dict[str, Any], chosen: dict[str, Any], gates: list[str]) -> None:
    decision_log.record(
        ctx.conn, pub["workspace_id"], "publish",
        {"platform": pub.get("platform"), "scheduled": bool(pub.get("scheduled_for")), "connection": bool(pub.get("connection_id")), "gates_failed": gates},
        [], chosen, actor_type="system", brand_profile_id=pub.get("brand_profile_id"), source_id=pub.get("source_id"),
        candidate_id=pub.get("candidate_id"), clip_id=pub.get("clip_id"),
    )  # fmt: skip


# -- Publish -------------------------------------------------------------------------------------
def run_publish_clip(ctx: common.Context, publication_id: str, http=None) -> dict[str, Any]:
    """Gates prüfen, ``/api/internal/publish`` aufrufen, Ergebnis schreiben. Idempotent bei ``published``."""
    pub = load_publication(ctx, publication_id)
    if pub["status"] == "published":
        return {"publication_id": publication_id, "status": "published", "external_id": pub.get("external_id"), "external_url": pub.get("external_url"), "published_at": pub.get("published_at"), "skipped": True}
    if pub["status"] not in PUBLISHABLE_STATUSES:
        return {"publication_id": publication_id, "status": pub["status"], "skipped": True, "error": f"Status {pub['status']} wird nicht veröffentlicht"}

    gates = check_gates(ctx, pub)
    if gates:
        error = "Veröffentlichung gesperrt: " + "; ".join(gates)
        _set(ctx, publication_id, status="failed", error=error)
        pub.update(status="failed", error=error)
        outbox.publication_event(ctx.conn, pub["workspace_id"], pub, "failed")
        _log_publish(ctx, pub, {"status": "failed", "reason": "gates"}, gates)
        log.warning("publish blocked publication=%s gates=%s", publication_id, len(gates))
        return {"publication_id": publication_id, "status": "failed", "error": error, "gates": gates}

    _set(ctx, publication_id, status="publishing", error=None)
    try:
        result = internal_api.publish(publication_id, ctx.settings, http)
    except Exception as exc:
        error = f"Web-App nicht erreichbar: {exc.__class__.__name__}: {str(exc)[:200]}"
        _set(ctx, publication_id, status="failed", error=error)
        pub.update(status="failed", error=error)
        outbox.publication_event(ctx.conn, pub["workspace_id"], pub, "failed")
        raise

    if result["status"] == "published":
        published_at = _now()
        _set(
            ctx, publication_id, status="published", external_id=result.get("external_id"),
            external_url=result.get("external_url"), published_at=published_at, error=None,
        )  # fmt: skip
        pub.update(status="published", external_id=result.get("external_id"), external_url=result.get("external_url"), published_at=published_at.isoformat())
        outbox.publication_event(ctx.conn, pub["workspace_id"], pub, "published")
        _log_publish(ctx, pub, {"status": "published", "external_id": result.get("external_id")}, [])
        log.info("published publication=%s platform=%s", publication_id, pub.get("platform"))
        return {"publication_id": publication_id, "status": "published", "external_id": result.get("external_id"), "external_url": result.get("external_url"), "published_at": published_at.isoformat()}

    error = str(result.get("error") or "Veröffentlichung fehlgeschlagen")
    _set(ctx, publication_id, status="failed", error=error)
    pub.update(status="failed", error=error)
    outbox.publication_event(ctx.conn, pub["workspace_id"], pub, "failed")
    _log_publish(ctx, pub, {"status": "failed", "reason": "provider"}, [])
    log.warning("publish failed publication=%s", publication_id)
    return {"publication_id": publication_id, "status": "failed", "error": error}


def run_cancel_publication(ctx: common.Context, publication_id: str) -> dict[str, Any]:
    """Abbruch vor dem Publish: ``scheduled`` wird ``failed`` mit Hinweis; alles andere bleibt unverändert."""
    pub = load_publication(ctx, publication_id)
    if pub["status"] != "scheduled":
        return {"publication_id": publication_id, "status": pub["status"], "cancelled": False}
    _set(ctx, publication_id, status="failed", error="Veröffentlichung abgebrochen")
    return {"publication_id": publication_id, "status": "failed", "cancelled": True}


# -- Metriken und Reward -------------------------------------------------------------------------
def per_1k(numerator: Any, views: Any) -> float | None:
    if numerator is None or views is None or float(views) <= 0:
        return None
    return round(float(numerator) / float(views) * 1000.0, 4)


def _median(values: list[Any]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return float(statistics.median(vals)) if vals else None


def _norm(value: float | None, median: float | None) -> float | None:
    """Wert relativ zum Account-Median, auf ``NORM_CAP`` gedeckelt. Ohne Historie 1,0 (neutral)."""
    if value is None:
        return None
    if median is None:
        return 1.0
    if median <= 0:
        return NORM_CAP if value > 0 else 1.0
    return round(min(NORM_CAP, value / median), 4)


def compute_reward(metrics: dict[str, Any], history: list[tuple[Any, Any, Any]]) -> dict[str, Any]:
    """Abgeleitete Kennzahlen und Reward aus Metriken und Account-Historie ``[(views, follows_per_1k, saves_per_1k)]``."""
    views = metrics.get("views")
    f1k = per_1k(metrics.get("follows"), views)
    s1k = per_1k(metrics.get("saves"), views)
    median_views = _median([h[0] for h in history])
    outlier = round(float(views) / median_views, 4) if views is not None and median_views else None
    norms = {
        "follows": _norm(f1k, _median([h[1] for h in history])),
        "saves": _norm(s1k, _median([h[2] for h in history])),
        "outlier": min(NORM_CAP, outlier) if outlier is not None else None,
    }
    present = {k: v for k, v in norms.items() if v is not None}
    reward = None
    if present:
        total_w = sum(REWARD_WEIGHTS[k] for k in present)
        reward = round(sum(REWARD_WEIGHTS[k] * v for k, v in present.items()) / total_w, 4)
    return {
        "follows_per_1k": f1k,
        "saves_per_1k": s1k,
        "account_median_views": median_views,
        "outlier_score": outlier,
        "reward": reward,
        "norms": norms,
        "history_n": len(history),
    }


def account_history(ctx: common.Context, pub: dict[str, Any]) -> list[tuple[Any, Any, Any]]:
    return [
        tuple(r) for r in db.fetch_all(
            ctx.conn, SQL_ACCOUNT_HISTORY,
            (pub["workspace_id"], pub.get("platform"), pub.get("connection_id") or "", pub["id"], HISTORY_LIMIT),
        )
    ]  # fmt: skip


def run_fetch_metrics(ctx: common.Context, publication_id: str, window: str, http=None) -> dict[str, Any]:
    """Metriken eines Fensters holen, ``performance_feedback`` schreiben (Upsert), ``publications.metrics`` ergänzen."""
    if window not in METRIC_WINDOWS:
        raise ValueError(f"Unbekanntes Metrik-Fenster {window!r}")
    pub = load_publication(ctx, publication_id)
    if pub["status"] != "published":
        raise RuntimeError(f"Publikation {publication_id} ist nicht veröffentlicht (Status {pub['status']})")
    metrics = internal_api.metrics(publication_id, window, ctx.settings, http)
    derived = write_window_feedback(ctx, pub, window, metrics)
    log.info("metrics publication=%s window=%s views=%s reward=%s", publication_id, window, metrics.get("views"), derived["reward"])
    return {"publication_id": publication_id, "window": window, **derived}


def write_window_feedback(ctx: common.Context, pub: dict[str, Any], window: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """``performance_feedback`` für ein Fenster schreiben (Upsert) und ``publications.metrics`` ergänzen.

    Gemeinsam für ``run_fetch_metrics`` (feste Fenster aus dem PublishWorkflow) und die Brücke aus der
    Messreihe (``run_snapshot``). Gibt die abgeleiteten Kennzahlen samt ``feedback_id`` zurück."""
    publication_id = pub["id"]
    derived = compute_reward(metrics, account_history(ctx, pub))
    now = _now()
    values = {
        "views": metrics.get("views"),
        "likes": metrics.get("likes"),
        "comments": metrics.get("comments"),
        "shares": metrics.get("shares"),
        "saves": metrics.get("saves"),
        "follows": metrics.get("follows"),
        "avg_watch_time_s": metrics.get("avg_watch_time_s"),
        "retention_curve": db.jsonb(metrics.get("retention_curve")) if metrics.get("retention_curve") is not None else None,
        "follows_per_1k": derived["follows_per_1k"],
        "saves_per_1k": derived["saves_per_1k"],
        "account_median_views": derived["account_median_views"],
        "outlier_score": derived["outlier_score"],
        "reward": derived["reward"],
        "fetched_at": now,
    }
    existing = db.fetch_one(ctx.conn, SQL_FEEDBACK_ID, (publication_id, window))
    if existing is None:
        row = db.insert(
            ctx.conn, "performance_feedback", returning="id",
            workspace_id=pub["workspace_id"], clip_id=pub["clip_id"], publication_id=publication_id,
            platform=pub.get("platform"), metric_window=window, **values,
        )  # fmt: skip
        feedback_id = str(row[0]) if row else ""
    else:
        feedback_id = str(existing[0])
        db.update(ctx.conn, "performance_feedback", {"id": feedback_id}, **values)
    merged = dict(pub.get("metrics") or {})
    merged[f"at_{window}"] = {**metrics, "follows_per_1k": derived["follows_per_1k"], "saves_per_1k": derived["saves_per_1k"], "reward": derived["reward"]}
    _set(ctx, publication_id, metrics=db.jsonb(merged), metrics_fetched_at=now)
    pub["metrics"] = merged
    return {"feedback_id": feedback_id, **derived}


# -- Messreihe (Migration 0019) ------------------------------------------------------------------
# Zeitplan der Messungen nach Alter der Publikation: stündlich bis 6 h, alle 6 h bis 48 h, danach täglich
# bis tracking_until. Ohne tracking_until gilt published_at + DEFAULT_TRACK_DAYS.
HOUR_S = 3600
SNAPSHOT_SCHEDULE = ((6 * HOUR_S, 1 * HOUR_S), (48 * HOUR_S, 6 * HOUR_S), (None, 24 * HOUR_S))
DEFAULT_TRACK_DAYS = 30
# Brücke zu den festen Fenstern: Alter, ab dem eine Messung als Fenster zählt.
WINDOW_AGES = (("6h", 6 * HOUR_S), ("48h", 48 * HOUR_S), ("7d", 7 * 24 * HOUR_S))
# Eine Messung zählt nur für ein Fenster, solange sie jünger als das Doppelte des Fensters ist: wer einen Link
# erst nach zehn Tagen einträgt, bekommt kein 6h- und kein 48h-Fenster mit Zehn-Tage-Zahlen (die würden den
# Account-Median und damit den Reward verzerren). Der Zeitplan oben trifft jedes Fenster innerhalb dieser Spanne.
WINDOW_MAX_FACTOR = 2.0
SNAPSHOT_METRICS = ("views", "engaged_views", "likes", "comments", "shares", "saves", "follows", "reach", "avg_watch_time_s", "skip_rate")
SNAPSHOT_STATUSES = {"oauth": ("published",), "link": ("published", "manual")}

SQL_SNAPSHOT_PUBLICATION = (
    "select p.id, coalesce(p.workspace_id, s.workspace_id), p.clip_id, p.connection_id, p.platform, p.status, "
    "p.published_at, p.created_at, p.tracking, p.tracking_until, p.metrics, s.brand_profile_id "
    "from publications p join clips c on c.id = p.clip_id join sources s on s.id = c.source_id where p.id = %s"
)


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def next_snapshot_at(published_at: datetime, now: datetime, tracking_until: datetime | None) -> datetime | None:
    """Nächste fällige Messung nach ``SNAPSHOT_SCHEDULE``; ``None``, wenn ``tracking_until`` erreicht ist.

    Die letzte Messung fällt genau auf ``tracking_until``, damit das Ende der Messreihe nicht davon abhängt,
    wie der Tagesrhythmus zufällig liegt."""
    until = tracking_until or (published_at + timedelta(days=DEFAULT_TRACK_DAYS))
    if now >= until:
        return None
    age_s = max(0.0, (now - published_at).total_seconds())
    step = next(step for limit, step in SNAPSHOT_SCHEDULE if limit is None or age_s < limit)
    return min(now + timedelta(seconds=step), until)


def window_hint(age_s: float) -> str:
    """Welches feste Fenster der Messung am nächsten liegt (Hinweis an Provider mit Zeitraum)."""
    if age_s < 6 * HOUR_S:
        return "6h"
    if age_s < 48 * HOUR_S:
        return "48h"
    return "7d"


def due_window(age_s: float | None, written: set[str]) -> str | None:
    """Fenster, das diese Messung zum ersten Mal erreicht (und noch nicht geschrieben ist), sonst ``None``."""
    if age_s is None:
        return None
    for window, limit in reversed(WINDOW_AGES):
        if limit <= age_s < limit * WINDOW_MAX_FACTOR and window not in written:
            return window
    return None


def load_snapshot_publication(ctx: common.Context, publication_id: str) -> dict[str, Any] | None:
    row = db.fetch_one(ctx.conn, SQL_SNAPSHOT_PUBLICATION, (publication_id,))
    if row is None:
        return None
    keys = [
        "id", "workspace_id", "clip_id", "connection_id", "platform", "status", "published_at", "created_at",
        "tracking", "tracking_until", "metrics", "brand_profile_id",
    ]  # fmt: skip
    out = dict(zip(keys, row))
    for k in ("id", "workspace_id", "clip_id", "connection_id", "brand_profile_id"):
        out[k] = str(out[k]) if out.get(k) else None
    out["metrics"] = dict(_json(out.get("metrics"), {}) or {})
    out["tracking"] = out.get("tracking") or "oauth"
    return out


def _written_windows(ctx: common.Context, publication_id: str) -> set[str]:
    return {w for w, _a in WINDOW_AGES if db.fetch_one(ctx.conn, SQL_FEEDBACK_ID, (publication_id, w)) is not None}


def run_snapshot(ctx: common.Context, publication_id: str, http=None) -> dict[str, Any]:
    """Eine Messung: ``/api/internal/metrics`` im Modus snapshot, Zeile in ``metric_snapshots``, nächster Termin.

    Wirft nie wegen der Plattform oder der Web-App: Fehler stehen in ``metric_snapshots.error`` und der
    Zeitplan läuft weiter. Erreicht die Messung zum ersten Mal 6h, 48h oder 7d (siehe ``due_window``),
    schreibt sie zusätzlich das feste Fenster in ``performance_feedback`` mit Reward."""
    pub = load_snapshot_publication(ctx, publication_id)
    if pub is None:
        return {"publication_id": publication_id, "status": "missing"}
    now = _now()
    allowed = SNAPSHOT_STATUSES.get(pub["tracking"], ())
    if pub["status"] not in allowed:
        _set(ctx, publication_id, next_snapshot_at=None)
        return {"publication_id": publication_id, "status": "skipped", "reason": f"Status {pub['status']} wird bei tracking {pub['tracking']} nicht gemessen"}

    published_at = _as_dt(pub.get("published_at")) or _as_dt(pub.get("created_at")) or now
    age_s = max(0, int((now - published_at).total_seconds()))
    error: str | None = None
    try:
        result = internal_api.snapshot(publication_id, window_hint(age_s), ctx.settings, http)
    except Exception as exc:  # Web-App weg oder kaputte Antwort: als Fehlerzeile festhalten, Zeitplan weiter
        result = {"metrics": {}, "source": "oauth" if pub["tracking"] == "oauth" else "public_api", "raw": None, "error": None}
        error = f"Web-App nicht erreichbar: {exc.__class__.__name__}: {str(exc)[:200]}"
    metrics = result.get("metrics") or {}
    error = error or result.get("error")
    has_numbers = any(metrics.get(k) is not None for k in SNAPSHOT_METRICS)

    values: dict[str, Any] = {k: metrics.get(k) for k in SNAPSHOT_METRICS}
    db.insert(
        ctx.conn, "metric_snapshots",
        workspace_id=pub["workspace_id"], publication_id=publication_id, fetched_at=now, age_s=age_s,
        source=result.get("source") or "oauth", **values,
        retention_curve=db.jsonb(metrics.get("retention_curve")) if metrics.get("retention_curve") is not None else None,
        raw=db.jsonb(result.get("raw")) if result.get("raw") is not None else None,
        error=(str(error)[:500] if error else None),
    )  # fmt: skip

    window = None
    reward = None
    if has_numbers:
        window = due_window(age_s, _written_windows(ctx, publication_id))
        if window:
            bridge = {k: metrics.get(k) for k in internal_api.METRIC_KEYS}
            reward = write_window_feedback(ctx, {**pub, "id": publication_id}, window, bridge)["reward"]

    tracking_until = _as_dt(pub.get("tracking_until"))
    nxt = next_snapshot_at(published_at, now, tracking_until)
    _set(ctx, publication_id, next_snapshot_at=nxt, metrics_fetched_at=now)
    log.info(
        "snapshot publication=%s age_s=%s source=%s views=%s window=%s error=%s",
        publication_id, age_s, result.get("source"), metrics.get("views"), window, bool(error),
    )  # fmt: skip
    return {
        "publication_id": publication_id,
        "status": "ok" if has_numbers and not error else ("error" if error else "empty"),
        "age_s": age_s,
        "window": window,
        "reward": reward,
        "error": error,
        "next_snapshot_at": nxt.isoformat() if nxt else None,
    }


# TODO Temporal: PublishWorkflow (workflows/publish.py) holt weiterhin nur die festen Fenster 6h, 48h und 7d.
# Link-Tracking (tracking = 'link') und die Messreihe laufen über local_worker.process_metrics; im Temporal-Betrieb
# braucht es dafür später einen geplanten Workflow, der run_snapshot für fällige Publikationen aufruft.


# -- Activities ----------------------------------------------------------------------------------
@activity.defn(name="load_publication")
def load_publication_activity(publication_id: str) -> dict:
    ctx = common.open_context()
    try:
        pub = load_publication(ctx, publication_id)
        return {k: pub[k] for k in ("id", "workspace_id", "clip_id", "platform", "status", "scheduled_for", "published_at")}
    finally:
        ctx.close()


@activity.defn(name="publish_clip")
def publish_clip(publication_id: str) -> dict:
    ctx = common.open_context()
    try:
        return run_publish_clip(ctx, publication_id)
    finally:
        ctx.close()


@activity.defn(name="fetch_metrics")
def fetch_metrics(publication_id: str, window: str) -> dict:
    ctx = common.open_context()
    try:
        return run_fetch_metrics(ctx, publication_id, window)
    finally:
        ctx.close()


@activity.defn(name="cancel_publication")
def cancel_publication(publication_id: str) -> dict:
    ctx = common.open_context()
    try:
        return run_cancel_publication(ctx, publication_id)
    finally:
        ctx.close()


__all__ = [
    "HISTORY_LIMIT",
    "METRIC_WINDOWS",
    "NORM_CAP",
    "PUBLISHABLE_CLIP_STATUSES",
    "REWARD_WEIGHTS",
    "account_history",
    "cancel_publication",
    "check_gates",
    "compute_reward",
    "due_window",
    "fetch_metrics",
    "load_publication",
    "load_publication_activity",
    "load_snapshot_publication",
    "next_snapshot_at",
    "per_1k",
    "publish_clip",
    "run_cancel_publication",
    "run_fetch_metrics",
    "run_publish_clip",
    "run_snapshot",
    "window_hint",
    "write_window_feedback",
]
