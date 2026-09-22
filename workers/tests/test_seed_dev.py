"""Seed-Skript (scripts/seed_dev.py): idempotent gegen eine kleine tabellenbasierte Fake-Verbindung, Argon2id-Format."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

import pytest

from scripts import seed_dev


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.rowcount = len(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class TableConn:
    """Generischer Fake: ``insert into <t> (...)`` legt Zeilen an, ``select ... from <t> where a = %s and b = %s`` filtert."""

    def __init__(self):
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.rows["plans"].append({"code": "starter", "included_hours": 4, "overage_eur_per_hour": 9.0})

    def execute(self, sql: str, params=()):
        q = " ".join(sql.split())
        low = q.lower()
        if low.startswith("insert into"):
            table = q.split()[2]
            cols = [c.strip() for c in q.split("(", 1)[1].split(")", 1)[0].split(",")]
            row = {c: (getattr(v, "obj", v)) for c, v in zip(cols, params)}
            row.setdefault("id", str(uuid.uuid4()))
            self.rows[table].append(row)
            return _Cur([(row["id"],)])
        if low.startswith("update "):
            table = q.split()[1]
            set_part = q.split(" set ", 1)[1].split(" where ", 1)[0]
            cols = [c.split("=")[0].strip() for c in set_part.split(",")]
            for r in self.rows[table]:
                if r.get("id") == params[-1]:
                    for c, v in zip(cols, params[: len(cols)]):
                        r[c] = getattr(v, "obj", v)
            return _Cur([])
        if low.startswith("select"):
            select_cols = [c.strip() for c in q[len("select ") :].split(" from ", 1)[0].split(",")]
            rest = q.split(" from ", 1)[1]
            table = rest.split()[0]
            where = rest.split(" where ", 1)[1] if " where " in rest else ""
            conds = [c.strip().split(" = ")[0] for c in where.split(" and ")] if where else []
            matches = [r for r in self.rows[table] if all(r.get(c) == v for c, v in zip(conds, params))]
            return _Cur([tuple(r.get(c, 1 if c == "1" else None) for c in select_cols) for r in matches])
        raise AssertionError(f"TableConn kennt diese Abfrage nicht: {q[:60]}")

    def close(self):
        pass


def test_seed_is_idempotent():
    conn = TableConn()
    now = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)
    first = seed_dev.seed(conn, now=now, password_hash="$argon2id$v=19$m=65536,t=3,p=4$c$h")
    assert {k: v for k, v in first.items() if k not in ("workspace_id", "user_id")} == dict.fromkeys(
        ["user", "workspace", "membership", "brand_profile", "subscription", "usage_period"], "angelegt"
    )
    second = seed_dev.seed(conn, now=now, password_hash="unused")
    assert {k: v for k, v in second.items() if k not in ("workspace_id", "user_id")} == dict.fromkeys(
        ["user", "workspace", "membership", "brand_profile", "subscription", "usage_period"], "vorhanden"
    )
    assert second["workspace_id"] == first["workspace_id"] and second["user_id"] == first["user_id"]

    user = conn.rows["users"][0]
    assert user["email"] == "dev@chopstr.local" and user["password_hash"].startswith("$argon2id$") and user["locale"] == "de-AT"
    ws = conn.rows["workspaces"][0]
    assert ws["name"] == "PLACEMedia" and ws["slug"] == "placemedia" and ws["plan"] == "starter"
    member = conn.rows["workspace_members"][0]
    assert member["role"] == "owner" and member["user_id"] == user["id"] and member["workspace_id"] == ws["id"]
    brand = conn.rows["brand_profiles"][0]
    assert brand["name"] == "PLACEMedia" and brand["ci"]["fonts"]["fallback"] == "Inter" and brand["country"] == "AT"
    sub = conn.rows["subscriptions"][0]
    assert sub["plan_code"] == "starter" and sub["status"] == "trialing" and (sub["trial_ends_at"] - now).days == 14
    period = conn.rows["usage_periods"][0]
    assert period["included_minutes"] == 240.0 and str(period["period_start"]) == "2026-09-01" and str(period["period_end"]) == "2026-09-30"
    assert len(conn.rows["usage_periods"]) == 1 and len(conn.rows["subscriptions"]) == 1


def test_password_hash_is_argon2id_phc_with_documented_params():
    argon2 = pytest.importorskip("argon2")
    h = seed_dev.hash_password("chopstr-dev")
    assert h.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert argon2.PasswordHasher().verify(h, "chopstr-dev") is True
    with pytest.raises(argon2.exceptions.VerifyMismatchError):
        argon2.PasswordHasher().verify(h, "falsch")


def test_main_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert seed_dev.main([]) == 2
    assert "DATABASE_URL" in capsys.readouterr().err
