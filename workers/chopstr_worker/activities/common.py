"""Gemeinsame Helfer für Activities: Laufzeitkontext (DB, Storage, Arbeitsordner), Keys, Heartbeat."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config, db, ingest, storage

log = logging.getLogger("chopstr.activities")


@dataclass
class Context:
    """Ein Kontext pro Activity-Aufruf. ``conn`` kann in Tests eine Fake-DB sein."""

    conn: Any
    store: storage.Storage
    settings: config.Settings
    work_dir: Path

    def source_dir(self, source_id: str) -> Path:
        p = self.work_dir / source_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.conn.close()


_OVERRIDE: dict[str, Any] = {}


def set_context_factory(factory) -> None:
    """Tests können hier eine Factory setzen, die einen ``Context`` ohne Postgres/S3 liefert."""
    _OVERRIDE["factory"] = factory


def open_context() -> Context:
    if "factory" in _OVERRIDE:
        return _OVERRIDE["factory"]()
    s = config.settings()
    base = Path(s.work_dir or os.path.join(tempfile.gettempdir(), "chopstr-work"))
    base.mkdir(parents=True, exist_ok=True)
    return Context(conn=db.connect(s.database_url), store=storage.Storage(s), settings=s, work_dir=base)


def heartbeat(*details: Any) -> None:
    """Temporal-Heartbeat, wenn wir in einer Activity laufen; sonst still."""
    try:
        from temporalio import activity

        if activity.in_activity():
            activity.heartbeat(*details)
    except Exception:  # pragma: no cover
        pass


def audio_key_for(storage_key: str) -> str:
    return storage.derived_key(storage_key, ingest.AUDIO_PARAMS, ingest.INGEST_VERSION, "wav", prefix="audio")


def proxy_key_for(storage_key: str) -> str:
    return storage.derived_key(storage_key, ingest.PROXY_PARAMS, ingest.INGEST_VERSION, "mp4", prefix="proxy")


def vocab_hash(vocab: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(vocab), ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def ensure_local_audio(ctx: Context, source_id: str, audio_key: str) -> Path:
    """Stellt sicher, dass die 16-kHz-WAV lokal liegt (Download aus dem Derived-Bucket)."""
    local = ctx.source_dir(source_id) / "audio16k.wav"
    if not local.is_file():
        ctx.store.download_to("derived", audio_key, local)
    return local


def require(source: dict, key: str, what: str) -> Any:
    val = source.get(key)
    if not val:
        raise RuntimeError(f"{what} fehlt (Spalte {key}). Wurde probe_and_extract ausgeführt?")
    return val


__all__ = [
    "Context",
    "audio_key_for",
    "ensure_local_audio",
    "heartbeat",
    "open_context",
    "proxy_key_for",
    "require",
    "set_context_factory",
    "vocab_hash",
]
