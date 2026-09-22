"""Datenbankzugriff (psycopg 3, autocommit).

Der Worker läuft mit der Rolle ``chopstr_worker`` (BYPASSRLS, siehe Migration 0001).
Alle Helfer nehmen ein ``conn``-Objekt, das die Methode ``execute(sql, params)`` mit
``fetchone()``/``fetchall()`` liefert. Damit funktioniert in Tests ein Fake-Objekt ohne Postgres.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Protocol

from . import config


class Connection(Protocol):
    def execute(self, query: str, params: Any = None) -> Any: ...

    def close(self) -> None: ...


def connect(dsn: str | None = None):
    """Öffnet eine autocommit-Verbindung. ``psycopg`` wird erst hier importiert."""
    import psycopg

    dsn = dsn or config.settings().database_url
    if not dsn:
        raise RuntimeError("DATABASE_URL ist nicht gesetzt")
    return psycopg.connect(dsn, autocommit=True)


def jsonb(value: Any):
    """Wrapper für JSONB-Parameter. Fällt ohne psycopg auf einen JSON-String zurück (Fake-DB in Tests)."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover
        return json.dumps(value, ensure_ascii=False)
    return Jsonb(value)


def fetch_one(conn: Connection, query: str, params: Iterable[Any] | None = None) -> tuple | None:
    return conn.execute(query, tuple(params or ())).fetchone()


def fetch_all(conn: Connection, query: str, params: Iterable[Any] | None = None) -> list[tuple]:
    return list(conn.execute(query, tuple(params or ())).fetchall())


def update(conn: Connection, table: str, where: dict[str, Any], **values: Any) -> None:
    """``update <table> set k=%s ... where k=%s``; JSON-Werte vorher mit ``jsonb()`` wrappen."""
    if not values:
        return
    set_sql = ", ".join(f"{k} = %s" for k in values)
    where_sql = " and ".join(f"{k} = %s" for k in where)
    conn.execute(f"update {table} set {set_sql} where {where_sql}", (*values.values(), *where.values()))


def insert(conn: Connection, table: str, returning: str | None = None, **values: Any) -> Any:
    cols = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    sql = f"insert into {table} ({cols}) values ({marks})"
    if returning:
        sql += f" returning {returning}"
        return conn.execute(sql, tuple(values.values())).fetchone()
    conn.execute(sql, tuple(values.values()))
    return None


def load_source(conn: Connection, source_id: str) -> dict[str, Any]:
    """Quelle plus Markenprofil und Workspace-Tier in einem Dict (Spaltennamen wie im Schema)."""
    row = fetch_one(
        conn,
        """
        select s.id, s.workspace_id, s.storage_key, s.audio_key, s.proxy_key, s.sha256, s.duration_s,
               s.width, s.height, s.fps, s.expected_speakers, s.brief, s.status, s.title,
               s.original_filename, s.mime_type, s.size_bytes,
               p.asr_variant, p.brand_vocab, p.protected_terms, p.country, p.address,
               w.tier, w.allow_us_subprocessors
        from sources s
        left join brand_profiles p on p.id = s.brand_profile_id
        join workspaces w on w.id = s.workspace_id
        where s.id = %s
        """,
        (source_id,),
    )
    if row is None:
        raise LookupError(f"Quelle {source_id} nicht gefunden")
    keys = [
        "id", "workspace_id", "storage_key", "audio_key", "proxy_key", "sha256", "duration_s",
        "width", "height", "fps", "expected_speakers", "brief", "status", "title",
        "original_filename", "mime_type", "size_bytes",
        "asr_variant", "brand_vocab", "protected_terms", "country", "address",
        "tier", "allow_us_subprocessors",
    ]  # fmt: skip
    out = dict(zip(keys, row))
    out["asr_variant"] = out.get("asr_variant") or "de"
    out["brand_vocab"] = list(out.get("brand_vocab") or [])
    out["protected_terms"] = list(out.get("protected_terms") or [])
    out["tier"] = out.get("tier") or config.TIER_STANDARD
    return out


__all__ = ["Connection", "connect", "fetch_all", "fetch_one", "insert", "jsonb", "load_source", "update"]
