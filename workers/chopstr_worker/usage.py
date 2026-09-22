"""Verbrauchsbuchung nach Stunden Quellmaterial (Tabelle ``usage_periods``, Vertrag PHASE4.md Abschnitt 5).

Eine Zeile pro Workspace und Kalendermonat (``period_start`` erster Tag, ``period_end`` letzter Tag des
Monats). ``included_minutes`` kommt aus dem Abo (``subscriptions.plan_code`` zu ``plans.included_hours``),
ohne Abo gilt der Starter-Wert. Mehrverbrauch wird pro angefangener Stunde berechnet:
``overage_eur = ceil(overage_minutes / 60) * plans.overage_eur_per_hour``.

Alle Funktionen nehmen eine ``conn`` mit ``execute()`` (psycopg oder Fake-DB in Tests). Kein Credit-System.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from . import db

DEFAULT_PLAN_CODE = "starter"
DEFAULT_INCLUDED_HOURS = 4.0
DEFAULT_OVERAGE_EUR_PER_HOUR = 9.0

SQL_PLAN_FOR_WORKSPACE = (
    "select p.code, p.included_hours, p.overage_eur_per_hour from subscriptions s "
    "join plans p on p.code = s.plan_code where s.workspace_id = %s"
)
SQL_PLAN_BY_CODE = "select code, included_hours, overage_eur_per_hour from plans where code = %s"
SQL_PERIOD = (
    "select id, included_minutes, used_source_minutes, overage_minutes from usage_periods "
    "where workspace_id = %s and period_start = %s"
)


@dataclass(frozen=True)
class PlanRates:
    code: str
    included_minutes: float
    overage_eur_per_hour: float


def period_bounds(at: datetime | date) -> tuple[date, date]:
    """Erster und letzter Tag des Kalendermonats von ``at`` (Zeitstempel werden in UTC gelesen)."""
    d = at.date() if isinstance(at, datetime) else at
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1), date(d.year, d.month, last)


def plan_rates(conn: db.Connection, workspace_id: str) -> PlanRates:
    """Tarifwerte des Workspace; ohne Abo der Starter-Tarif, ohne ``plans``-Zeile feste Starter-Defaults."""
    row = db.fetch_one(conn, SQL_PLAN_FOR_WORKSPACE, (workspace_id,))
    if row is None:
        row = db.fetch_one(conn, SQL_PLAN_BY_CODE, (DEFAULT_PLAN_CODE,))
    if row is None:
        return PlanRates(DEFAULT_PLAN_CODE, DEFAULT_INCLUDED_HOURS * 60.0, DEFAULT_OVERAGE_EUR_PER_HOUR)
    code, hours, eur = row
    return PlanRates(str(code), float(hours) * 60.0, float(eur))


def overage_eur(overage_minutes: float, eur_per_hour: float) -> float:
    """Mehrverbrauch pro angefangener Stunde."""
    if overage_minutes <= 0:
        return 0.0
    return round(math.ceil(overage_minutes / 60.0 - 1e-9) * eur_per_hour, 2)


def ensure_period(conn: db.Connection, workspace_id: str, at: datetime | None = None) -> dict[str, Any]:
    """Findet die ``usage_periods``-Zeile des Monats oder legt sie mit dem Kontingent des Tarifs an."""
    at = at or datetime.now(UTC)
    start, end = period_bounds(at)
    row = db.fetch_one(conn, SQL_PERIOD, (workspace_id, start))
    if row is not None:
        pid, included, used, overage = row
        return {
            "id": str(pid), "included_minutes": float(included or 0), "used_source_minutes": float(used or 0),
            "overage_minutes": float(overage or 0), "period_start": start, "period_end": end, "created": False,
        }  # fmt: skip
    rates = plan_rates(conn, workspace_id)
    inserted = db.insert(
        conn,
        "usage_periods",
        returning="id",
        workspace_id=workspace_id,
        period_start=start,
        period_end=end,
        included_minutes=round(rates.included_minutes, 2),
    )
    return {"id": str(inserted[0]), "included_minutes": rates.included_minutes, "used_source_minutes": 0.0, "overage_minutes": 0.0, "period_start": start, "period_end": end, "created": True}


def book_source_minutes(conn: db.Connection, workspace_id: str, minutes: float, at: datetime | None = None) -> dict[str, Any]:
    """Bucht ``minutes`` Quellmaterial auf den Monat von ``at`` und rechnet Mehrverbrauch neu."""
    minutes = max(0.0, float(minutes))
    period = ensure_period(conn, workspace_id, at)
    rates = plan_rates(conn, workspace_id)
    used = round(period["used_source_minutes"] + minutes, 2)
    over = round(max(0.0, used - period["included_minutes"]), 2)
    eur = overage_eur(over, rates.overage_eur_per_hour)
    db.update(conn, "usage_periods", {"id": period["id"]}, used_source_minutes=used, overage_minutes=over, overage_eur=eur)
    return {**period, "used_source_minutes": used, "overage_minutes": over, "overage_eur": eur, "plan_code": rates.code}


def book_render(conn: db.Connection, workspace_id: str, at: datetime | None = None) -> str:
    """Erhöht ``render_count`` des laufenden Monats um eins. Gibt die Perioden-ID zurück."""
    period = ensure_period(conn, workspace_id, at)
    conn.execute("update usage_periods set render_count = render_count + 1 where id = %s", (period["id"],))
    return period["id"]


def book_llm_tokens(conn: db.Connection, workspace_id: str, input_tokens: int, output_tokens: int, at: datetime | None = None) -> str:
    """Addiert Token auf den laufenden Monat (für ``cost_sink`` von Story-Engine und Copy-Engine)."""
    period = ensure_period(conn, workspace_id, at)
    conn.execute(
        "update usage_periods set llm_input_tokens = llm_input_tokens + %s, llm_output_tokens = llm_output_tokens + %s where id = %s",
        (int(input_tokens), int(output_tokens), period["id"]),
    )
    return period["id"]


def llm_sink(conn: db.Connection, workspace_id: str, collect: list[dict] | None = None):
    """``cost_sink``-Callable: sammelt die Nutzung (für ``job_costs``) und bucht Token auf die Periode."""

    def _sink(usage: dict[str, Any]) -> None:
        if collect is not None:
            collect.append(usage)
        book_llm_tokens(conn, workspace_id, int(usage.get("in", 0)), int(usage.get("out", 0)))

    return _sink


__all__ = [
    "DEFAULT_INCLUDED_HOURS",
    "DEFAULT_OVERAGE_EUR_PER_HOUR",
    "DEFAULT_PLAN_CODE",
    "PlanRates",
    "book_llm_tokens",
    "book_render",
    "book_source_minutes",
    "ensure_period",
    "llm_sink",
    "overage_eur",
    "period_bounds",
    "plan_rates",
]
