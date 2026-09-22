"""Wochenreport (Phase 5b): ``find_report_workspaces`` und ``build_weekly_report(workspace_id, week_start)``.

Grundlage sind die 7d-Zeilen aus ``performance_feedback``, deren Fenster in der Berichtswoche abgeschlossen
wurde (``fetched_at`` in [Montag, Montag + 7 Tage)). Drei beste und drei schwächste Clips nach
``follows_per_1k``, je Clip eine Ursache aus den Decision-Log-Merkmalen (Struktur, Hook-Muster, Länge,
Plattform, Rubrik) und eine konkrete Änderung als deutscher Textbaustein ohne Gedankenstriche. Ohne Daten
entsteht ein Bericht mit dem Hinweis „keine Publikationen mit Metriken“. Gespeichert in ``weekly_reports``
(Upsert je Workspace und Woche), Versand über ``/api/internal/mail`` an owner und admin.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from temporalio import activity

from .. import db, internal_api
from . import common

log = logging.getLogger("chopstr.activities.reports")

TOP_N = 3
NO_DATA_NOTE = "keine Publikationen mit Metriken"
LONG_CLIP_S = 60.0
WEAK_SCORE = 5

SQL_WEEK_ROWS = (
    "select f.clip_id, f.publication_id, f.platform, f.views, f.follows_per_1k, f.saves_per_1k, f.reward "
    "from performance_feedback f where f.workspace_id = %s and f.metric_window = '7d' "
    "and f.fetched_at >= %s and f.fetched_at < %s and f.clip_id is not null"
)
SQL_CLIP_INFO = (
    "select c.title_card, c.platform, c.candidate_id, c.duration_s, s.title "
    "from clips c join sources s on s.id = c.source_id where c.id = %s"
)
SQL_SCORED = "select features from decision_log where candidate_id = %s and decision_type = 'candidate_scored' order by created_at desc limit 1"
SQL_HOOK = "select chosen from decision_log where clip_id = %s and decision_type = 'hook_selected' order by created_at desc limit 1"
SQL_REPORT_ID = "select id from weekly_reports where workspace_id = %s and week_start = %s"
SQL_RECIPIENTS = (
    "select coalesce(u.email, m.email) from workspace_members m left join users u on u.id = m.user_id "
    "where m.workspace_id = %s and m.role in ('owner', 'admin')"
)
SQL_REPORT_WORKSPACES = "select id, name from workspaces where weekly_report_enabled"

STRUCTURE_LABELS = {
    "hook_build_payoff": "Hook, Aufbau, Payoff",
    "contrarian_claim": "Gegenthese",
    "decision_story": "Entscheidungsgeschichte",
    "how_to_list": "Anleitung als Liste",
    "loop": "Schleife",
}
PATTERN_LABELS = {
    "identity_call": "Ansprache der Zielgruppe",
    "contrarian": "Gegenposition",
    "open_loop": "offene Schleife",
    "results_first": "Ergebnis zuerst",
    "mistake_warning": "Fehlerwarnung",
}
PLATFORM_LABELS = {"linkedin": "LinkedIn", "tiktok": "TikTok", "reels": "Instagram Reels", "shorts": "YouTube Shorts", "instagram": "Instagram", "youtube": "YouTube", "manual": "manuell"}


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _label(mapping: dict[str, str], key: Any) -> str:
    return mapping.get(str(key or ""), str(key or "unbekannt"))


def _fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "keine Angabe"
    return f"{value:.{digits}f}".replace(".", ",")


def previous_week_start(now: datetime | date) -> date:
    """Montag der Vorwoche (Kalenderwoche vor ``now``)."""
    d = now.date() if isinstance(now, datetime) else now
    monday = d - timedelta(days=d.weekday())
    return monday - timedelta(days=7)


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=UTC)
    return start, start + timedelta(days=7)


def _parse_week(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# -- Einträge ------------------------------------------------------------------------------------
def clip_entry(ctx: common.Context, row: tuple) -> dict[str, Any]:
    clip_id, publication_id, platform, views, f1k, s1k, reward = row
    info = db.fetch_one(ctx.conn, SQL_CLIP_INFO, (str(clip_id),))
    title_card, clip_platform, candidate_id, duration_s, source_title = info if info else (None, None, None, None, None)
    feats: dict[str, Any] = {}
    if candidate_id:
        scored = db.fetch_one(ctx.conn, SQL_SCORED, (str(candidate_id),))
        feats = dict(_json(scored[0], {}) or {}) if scored else {}
    hook = db.fetch_one(ctx.conn, SQL_HOOK, (str(clip_id),))
    chosen = dict(_json(hook[0], {}) or {}) if hook else {}
    duration = feats.get("duration_s") if feats.get("duration_s") is not None else duration_s
    return {
        "clip_id": str(clip_id),
        "publication_id": str(publication_id) if publication_id else None,
        "title": (title_card or source_title or "Clip"),
        "platform": platform or clip_platform,
        "views": int(views) if views is not None else None,
        "follows_per_1k": float(f1k) if f1k is not None else None,
        "saves_per_1k": float(s1k) if s1k is not None else None,
        "reward": float(reward) if reward is not None else None,
        "features": {
            "structure": feats.get("structure"),
            "hook_pattern": chosen.get("pattern"),
            "duration_s": float(duration) if duration is not None else None,
            "platform": platform or clip_platform,
            "scores": dict(feats.get("scores") or {}),
        },
    }


def cause_text(entry: dict[str, Any], best: bool, top_patterns: list[str]) -> str:
    f = entry["features"]
    dur = f.get("duration_s")
    scores = f.get("scores") or {}
    dur_txt = f"{int(round(dur))} Sekunden" if dur is not None else "Länge unbekannt"
    base = (
        f"Struktur {_label(STRUCTURE_LABELS, f.get('structure'))}, Hook-Muster {_label(PATTERN_LABELS, f.get('hook_pattern'))}, "
        f"{dur_txt} auf {_label(PLATFORM_LABELS, f.get('platform'))}"
    )
    if best:
        return f"{base}: {_fmt(entry.get('follows_per_1k'))} Follower je 1.000 Views."
    if dur is not None and dur > LONG_CLIP_S:
        return f"{base}: zu lang für die Plattform ({dur_txt})."
    if scores.get("hook") is not None and int(scores["hook"]) < WEAK_SCORE:
        return f"{base}: schwacher Einstieg (Hook {int(scores['hook'])} von 10)."
    if scores.get("payoff") is not None and int(scores["payoff"]) < WEAK_SCORE:
        return f"{base}: schwacher Payoff ({int(scores['payoff'])} von 10)."
    if f.get("hook_pattern") and top_patterns and f.get("hook_pattern") not in top_patterns:
        return f"{base}: Hook-Muster liegt nicht unter den besten Mustern der Woche."
    return f"{base}: kein einzelnes Merkmal fällt ab, nur {_fmt(entry.get('follows_per_1k'))} Follower je 1.000 Views."


def change_text(entry: dict[str, Any], best: bool, top_patterns: list[str]) -> str:
    f = entry["features"]
    dur = f.get("duration_s")
    scores = f.get("scores") or {}
    if best:
        return "Struktur und Hook-Muster als Serie fortführen und eine Variante B mit gleichem Aufbau anlegen."
    if dur is not None and dur > LONG_CLIP_S:
        return "Auf unter 45 Sekunden kürzen und den Payoff früher setzen."
    if scores.get("hook") is not None and int(scores["hook"]) < WEAK_SCORE:
        return "Stärkeren Einstieg wählen, zum Beispiel Gegenposition oder Ergebnis zuerst als Variante B testen."
    if scores.get("payoff") is not None and int(scores["payoff"]) < WEAK_SCORE:
        return "Einen Kandidaten mit klarer Kernaussage wählen, der die Antwort im Clip liefert."
    if top_patterns and f.get("hook_pattern") not in top_patterns:
        return f"Hook-Muster {_label(PATTERN_LABELS, top_patterns[0])} wie beim besten Clip der Woche testen."
    return "Eine Variante B mit anderem Hook anlegen und nach 48 Stunden vergleichen."


def build_report(ctx: common.Context, workspace_id: str, week_start: date) -> dict[str, Any]:
    start, end = week_bounds(week_start)
    rows = db.fetch_all(ctx.conn, SQL_WEEK_ROWS, (workspace_id, start, end))
    entries = [clip_entry(ctx, r) for r in rows]
    entries = [e for e in entries if e.get("follows_per_1k") is not None]
    report: dict[str, Any] = {
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "clips": len(entries),
        "best": [],
        "weakest": [],
        "note": None,
    }
    if not entries:
        report["note"] = NO_DATA_NOTE
        return report
    ordered = sorted(entries, key=lambda e: (-(e["follows_per_1k"] or 0.0), -(e["views"] or 0)))
    best = ordered[:TOP_N]
    weakest = list(reversed(ordered[-TOP_N:])) if len(ordered) > TOP_N else []
    if len(ordered) <= TOP_N:
        weakest = list(reversed(ordered[1:])) if len(ordered) > 1 else []
    top_patterns = [b["features"]["hook_pattern"] for b in best if b["features"].get("hook_pattern")]
    for e in best:
        e["cause"] = cause_text(e, True, top_patterns)
        e["change"] = change_text(e, True, top_patterns)
    for e in weakest:
        e["cause"] = cause_text(e, False, top_patterns)
        e["change"] = change_text(e, False, top_patterns)
    report["best"] = best
    report["weakest"] = weakest
    return report


def render_text(report: dict[str, Any], workspace_name: str | None = None) -> tuple[str, str]:
    """Betreff und Klartext der Mail."""
    subject = f"chopstr Wochenreport {report['week_start']} bis {report['week_end']}"
    if workspace_name:
        subject += f" ({workspace_name})"
    lines = [f"Wochenreport {report['week_start']} bis {report['week_end']}", ""]
    if report.get("note"):
        lines.append(f"Hinweis: {report['note']}.")
        lines.append("Sobald Clips veröffentlicht und Metriken abgerufen wurden, enthält der Bericht die besten und schwächsten Clips.")
    else:
        lines.append(f"{report['clips']} Clips mit abgeschlossenem 7-Tage-Fenster.")
        lines += ["", "Beste Clips nach Folgequote:"]
        for i, e in enumerate(report["best"], start=1):
            lines.append(f"{i}. {e['title']} ({_label(PLATFORM_LABELS, e['platform'])}): {_fmt(e['follows_per_1k'])} Follower je 1.000 Views")
            lines.append(f"   Ursache: {e['cause']}")
            lines.append(f"   Änderung: {e['change']}")
        if report["weakest"]:
            lines += ["", "Schwächste Clips:"]
            for i, e in enumerate(report["weakest"], start=1):
                lines.append(f"{i}. {e['title']} ({_label(PLATFORM_LABELS, e['platform'])}): {_fmt(e['follows_per_1k'])} Follower je 1.000 Views")
                lines.append(f"   Ursache: {e['cause']}")
                lines.append(f"   Änderung: {e['change']}")
    lines += ["", "Abmelden: Einstellungen, Wochenreport."]
    return subject, "\n".join(lines)


def recipients(ctx: common.Context, workspace_id: str) -> list[str]:
    seen: list[str] = []
    for (email,) in db.fetch_all(ctx.conn, SQL_RECIPIENTS, (workspace_id,)):
        if email and str(email) not in seen:
            seen.append(str(email))
    return seen


def run_build_weekly_report(ctx: common.Context, workspace_id: str, week_start: str | date, send: bool = True, http=None) -> dict[str, Any]:
    """Bericht bauen, in ``weekly_reports`` speichern (Upsert), Mail an owner und admin."""
    ws_date = _parse_week(week_start)
    report = build_report(ctx, workspace_id, ws_date)
    existing = db.fetch_one(ctx.conn, SQL_REPORT_ID, (workspace_id, ws_date))
    if existing is None:
        row = db.insert(ctx.conn, "weekly_reports", returning="id", workspace_id=workspace_id, week_start=ws_date, report=db.jsonb(report))
        report_id = str(row[0]) if row else ""
    else:
        report_id = str(existing[0])
        db.update(ctx.conn, "weekly_reports", {"id": report_id}, report=db.jsonb(report))
    to = recipients(ctx, workspace_id) if send else []
    sent = False
    if to:
        subject, text = render_text(report)
        try:
            sent = internal_api.mail(to, subject, text, s=ctx.settings, http=http)
        except Exception as exc:  # Mailversand ist kein Grund, den Bericht zu verwerfen
            log.warning("weekly report mail failed workspace=%s error=%s", workspace_id, exc.__class__.__name__)
        if sent:
            db.update(ctx.conn, "weekly_reports", {"id": report_id}, sent_at=datetime.now(UTC))
    log.info("weekly report workspace=%s week=%s clips=%s sent=%s", workspace_id, ws_date, report["clips"], sent)
    return {"report_id": report_id, "workspace_id": workspace_id, "week_start": ws_date.isoformat(), "clips": report["clips"], "sent": sent, "recipients": len(to)}


def run_find_report_workspaces(ctx: common.Context) -> list[str]:
    return [str(r[0]) for r in db.fetch_all(ctx.conn, SQL_REPORT_WORKSPACES)]


@activity.defn(name="find_report_workspaces")
def find_report_workspaces() -> list[str]:
    ctx = common.open_context()
    try:
        return run_find_report_workspaces(ctx)
    finally:
        ctx.close()


@activity.defn(name="build_weekly_report")
def build_weekly_report(workspace_id: str, week_start: str) -> dict:
    ctx = common.open_context()
    try:
        return run_build_weekly_report(ctx, workspace_id, week_start)
    finally:
        ctx.close()


__all__ = [
    "NO_DATA_NOTE",
    "TOP_N",
    "build_report",
    "build_weekly_report",
    "cause_text",
    "change_text",
    "clip_entry",
    "find_report_workspaces",
    "previous_week_start",
    "recipients",
    "render_text",
    "run_build_weekly_report",
    "run_find_report_workspaces",
    "week_bounds",
]
