"""Seed für die lokale Entwicklung (Phase 4): ``python -m scripts.seed_dev`` mit ``DATABASE_URL``.

Legt an, falls nicht vorhanden (idempotent, jeder Schritt meldet „angelegt“ oder „vorhanden“):

- Nutzer ``dev@chopstr.local`` mit Passwort ``chopstr-dev`` (Argon2id über ``argon2-cffi``)
- Workspace „PLACEMedia“ (Slug ``placemedia``, Plan ``starter``, Tier ``standard``)
- Mitgliedschaft ``owner``
- Markenprofil „PLACEMedia“ (Anrede du, Land AT, Standardplattform LinkedIn)
- Abo ``starter`` im Status ``trialing`` mit 14 Tagen Test
- ``usage_periods`` für den aktuellen Kalendermonat

Passwort-Hash: PHC-String ``$argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>`` mit m = 65536 KiB, t = 3, p = 4,
32 Byte Hash, 16 Byte Salt. Dieselben Parameter wie ``@node-rs/argon2`` in der Web-App (Standard von
``hash()`` mit ``algorithm: Argon2id``); ``verify()`` dort liest die Parameter aus dem String, der Hash ist also
in beide Richtungen kompatibel. Das Skript läuft mit der Rolle ``chopstr_worker`` (BYPASSRLS).
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from chopstr_worker import db, usage

DEV_EMAIL = "dev@chopstr.local"
DEV_PASSWORD = "chopstr-dev"
DEV_NAME = "Dev Nutzer"
WORKSPACE_NAME = "PLACEMedia"
WORKSPACE_SLUG = "placemedia"
BRAND_NAME = "PLACEMedia"
PLAN_CODE = "starter"
TRIAL_DAYS = 14
ARGON2_PARAMS = {"time_cost": 3, "memory_cost": 65536, "parallelism": 4, "hash_len": 32, "salt_len": 16}
DEFAULT_CI: dict[str, Any] = {
    "colors": {"primary": "#111111", "secondary": "#F5F5F5", "accent": "#00D7FF"},
    "fonts": {"primary_asset_id": None, "secondary_asset_id": None, "fallback": "Inter"},
    "logo_asset_id": None,
    "watermark": {"enabled": False},
    "lower_third": {"enabled": False, "name": "", "function": "", "position": "bottom_left"},
    "hook_overlay": {"tiktok": True, "reels": True, "shorts": True, "linkedin": False},
}


def hash_password(password: str) -> str:
    """Argon2id-PHC-String mit den dokumentierten Parametern (m=65536, t=3, p=4)."""
    from argon2 import PasswordHasher
    from argon2.low_level import Type

    return PasswordHasher(**ARGON2_PARAMS, type=Type.ID).hash(password)


def _one(conn, sql: str, params: tuple) -> tuple | None:
    return db.fetch_one(conn, sql, params)


def seed(conn, now: datetime | None = None, password_hash: str | None = None) -> dict[str, str]:
    """Führt alle Schritte aus und gibt je Schritt „angelegt“ oder „vorhanden“ zurück (Schlüssel Englisch)."""
    now = now or datetime.now(UTC)
    report: dict[str, str] = {}

    row = _one(conn, "select id from users where email = %s", (DEV_EMAIL,))
    if row:
        user_id = str(row[0])
        report["user"] = "vorhanden"
    else:
        row = db.insert(
            conn, "users", returning="id",
            email=DEV_EMAIL, email_verified_at=now, password_hash=password_hash or hash_password(DEV_PASSWORD),
            display_name=DEV_NAME, locale="de-AT",
        )  # fmt: skip
        user_id = str(row[0])
        report["user"] = "angelegt"

    row = _one(conn, "select id from workspaces where slug = %s", (WORKSPACE_SLUG,))
    if row:
        workspace_id = str(row[0])
        report["workspace"] = "vorhanden"
    else:
        row = db.insert(conn, "workspaces", returning="id", name=WORKSPACE_NAME, slug=WORKSPACE_SLUG, plan=PLAN_CODE, tier="standard")
        workspace_id = str(row[0])
        report["workspace"] = "angelegt"

    row = _one(conn, "select 1 from workspace_members where workspace_id = %s and user_id = %s", (workspace_id, user_id))
    if row:
        report["membership"] = "vorhanden"
    else:
        db.insert(
            conn, "workspace_members",
            workspace_id=workspace_id, user_id=user_id, email=DEV_EMAIL, display_name=DEV_NAME, role="owner", accepted_at=now,
        )  # fmt: skip
        report["membership"] = "angelegt"

    row = _one(conn, "select id from brand_profiles where workspace_id = %s and name = %s", (workspace_id, BRAND_NAME))
    if row:
        report["brand_profile"] = "vorhanden"
    else:
        # caption_preset bleibt weg: NULL heißt „keine ausdrückliche Wahl“, das Format entscheidet
        # über den Untertitel-Stil (Migration 0007, activities/render.caption_preset_for).
        db.insert(
            conn, "brand_profiles", returning="id",
            workspace_id=workspace_id, name=BRAND_NAME, address="du", country="AT", asr_variant="de",
            default_platform="linkedin", brand_vocab=["chopstr", "PLACEMedia"],
            ci=db.jsonb(DEFAULT_CI),
        )  # fmt: skip
        report["brand_profile"] = "angelegt"

    row = _one(conn, "select id from subscriptions where workspace_id = %s", (workspace_id,))
    if row:
        report["subscription"] = "vorhanden"
    else:
        db.insert(
            conn, "subscriptions", returning="id",
            workspace_id=workspace_id, plan_code=PLAN_CODE, provider="manual", status="trialing",
            trial_ends_at=now + timedelta(days=TRIAL_DAYS), current_period_start=now,
            current_period_end=now + timedelta(days=TRIAL_DAYS), billing_email=DEV_EMAIL,
        )  # fmt: skip
        report["subscription"] = "angelegt"

    period = usage.ensure_period(conn, workspace_id, now)
    report["usage_period"] = "angelegt" if period["created"] else "vorhanden"
    report["workspace_id"] = workspace_id
    report["user_id"] = user_id
    return report


def main(argv: list[str] | None = None) -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL ist nicht gesetzt", file=sys.stderr)
        return 2
    conn = db.connect(dsn)
    try:
        report = seed(conn)
    finally:
        conn.close()
    labels = {
        "user": f"Nutzer {DEV_EMAIL} (Passwort {DEV_PASSWORD})",
        "workspace": f"Workspace {WORKSPACE_NAME}",
        "membership": "Mitgliedschaft owner",
        "brand_profile": f"Markenprofil {BRAND_NAME}",
        "subscription": f"Abo {PLAN_CODE} (trialing, {TRIAL_DAYS} Tage)",
        "usage_period": "Verbrauchsperiode für den aktuellen Monat",
    }
    for key, label in labels.items():
        print(f"{label}: {report[key]}")
    print(f"workspace_id={report['workspace_id']} user_id={report['user_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
