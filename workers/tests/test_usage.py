"""Verbrauchsbuchung nach Stunden (usage.py) mit Fake-DB: Monatsgrenze, angefangene Stunden, ohne Abo."""

from __future__ import annotations

from datetime import UTC, date, datetime

from chopstr_worker import usage


def test_period_bounds_cover_calendar_month():
    assert usage.period_bounds(datetime(2026, 2, 10, 12, 0, tzinfo=UTC)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert usage.period_bounds(date(2028, 2, 29)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert usage.period_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_overage_rounds_up_to_started_hours():
    assert usage.overage_eur(0, 9.0) == 0.0
    assert usage.overage_eur(1, 9.0) == 9.0
    assert usage.overage_eur(60, 9.0) == 9.0
    assert usage.overage_eur(60.5, 9.0) == 18.0
    assert usage.overage_eur(125, 7.5) == 22.5


def test_book_creates_period_with_plan_minutes(fake_db):
    wid = fake_db.add_workspace()
    fake_db.add_subscription(wid, "pro")
    r = usage.book_source_minutes(fake_db, wid, 30.0, at=datetime(2026, 9, 10, tzinfo=UTC))
    assert r["created"] is True and r["plan_code"] == "pro"
    assert r["included_minutes"] == 720.0 and r["used_source_minutes"] == 30.0 and r["overage_eur"] == 0.0
    row = fake_db.usage_periods[r["id"]]
    assert row["period_start"] == date(2026, 9, 1) and row["period_end"] == date(2026, 9, 30)
    assert row["included_minutes"] == 720.0 and row["used_source_minutes"] == 30.0
    # zweite Buchung im selben Monat: dieselbe Zeile
    r2 = usage.book_source_minutes(fake_db, wid, 12.5, at=datetime(2026, 9, 28, tzinfo=UTC))
    assert r2["id"] == r["id"] and r2["created"] is False and r2["used_source_minutes"] == 42.5
    assert len(fake_db.usage_periods) == 1


def test_without_subscription_starter_applies(fake_db):
    wid = fake_db.add_workspace()
    r = usage.book_source_minutes(fake_db, wid, 10.0)
    assert r["plan_code"] == "starter" and r["included_minutes"] == 240.0


def test_without_plans_table_defaults_apply(fake_db):
    fake_db.plans.clear()
    wid = fake_db.add_workspace()
    rates = usage.plan_rates(fake_db, wid)
    assert rates.code == "starter" and rates.included_minutes == 240.0 and rates.overage_eur_per_hour == 9.0


def test_month_boundary_opens_new_period(fake_db):
    wid = fake_db.add_workspace()
    a = usage.book_source_minutes(fake_db, wid, 100.0, at=datetime(2026, 9, 30, 23, 30, tzinfo=UTC))
    b = usage.book_source_minutes(fake_db, wid, 5.0, at=datetime(2026, 10, 1, 0, 30, tzinfo=UTC))
    assert a["id"] != b["id"] and b["created"] is True
    assert fake_db.usage_periods[a["id"]]["used_source_minutes"] == 100.0
    assert fake_db.usage_periods[b["id"]]["used_source_minutes"] == 5.0
    assert fake_db.usage_periods[b["id"]]["period_start"] == date(2026, 10, 1)


def test_overage_is_recomputed_per_started_hour(fake_db):
    wid = fake_db.add_workspace()  # Starter: 240 Minuten, 9 EUR je angefangene Stunde
    at = datetime(2026, 9, 5, tzinfo=UTC)
    r = usage.book_source_minutes(fake_db, wid, 250.0, at=at)
    assert r["overage_minutes"] == 10.0 and r["overage_eur"] == 9.0
    r = usage.book_source_minutes(fake_db, wid, 50.0, at=at)  # 300 gesamt: 60 Minuten Mehrverbrauch, genau eine Stunde
    assert r["overage_minutes"] == 60.0 and r["overage_eur"] == 9.0
    r = usage.book_source_minutes(fake_db, wid, 0.5, at=at)  # 60,5 Minuten: zweite Stunde angefangen
    assert r["overage_minutes"] == 60.5 and r["overage_eur"] == 18.0
    row = fake_db.usage_periods[r["id"]]
    assert row["overage_minutes"] == 60.5 and row["overage_eur"] == 18.0


def test_render_and_token_bookings(fake_db):
    wid = fake_db.add_workspace()
    at = datetime(2026, 9, 5, tzinfo=UTC)
    pid = usage.book_render(fake_db, wid, at=at)
    usage.book_render(fake_db, wid, at=at)
    usage.book_llm_tokens(fake_db, wid, 1200, 300, at=at)
    row = fake_db.usage_periods[pid]
    assert row["render_count"] == 2 and row["llm_input_tokens"] == 1200 and row["llm_output_tokens"] == 300
    collected: list[dict] = []
    sink = usage.llm_sink(fake_db, wid, collected)
    sink({"provider": "local-heuristic", "model": "heuristic-v1", "in": 10, "out": 5})
    assert collected and collected[0]["in"] == 10
    # der Sink bucht auf den laufenden Monat (ohne "at"); über alle Perioden stimmt die Summe
    assert sum(r["llm_input_tokens"] for r in fake_db.usage_periods.values()) == 1210
    assert sum(r["llm_output_tokens"] for r in fake_db.usage_periods.values()) == 305
