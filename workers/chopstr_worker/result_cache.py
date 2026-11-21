"""Ergebnis-Cache je Quelle, Stufe und Eingabe-Hash (T2).

Damit ein zweiter Lauf über dieselbe Quelle nichts doppelt rechnet: jedes Stufenergebnis (MM-Scan je Fenster,
Vorfilter je Block, Editor je Kandidat, Richter je Clip) liegt unter einem deterministischen Key aus
``storage.derived_key``: ``<prefix>/<stufe>/<sha256(quelle + {stufe, eingabe_sha256} + version)>.json``.

Zwei Ablagen mit derselben Schnittstelle (``key``, ``get``, ``put``):

- ``ResultCache(root=Path)``: Ordner, z. B. ``.local/eval-cache/<hash>/results`` für die Trainingsläufe.
- ``ResultCache(store=storage.Storage())``: Objektspeicher (Bucket ``derived``) für den Worker.

Ein unlesbarer Eintrag gilt als Fehltreffer und wird beim nächsten ``put`` überschrieben.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from . import storage

log = logging.getLogger("chopstr.result_cache")


def input_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ResultCache:
    def __init__(self, root: str | Path | None = None, store: Any = None, prefix: str = "results"):
        if root is None and store is None:
            raise ValueError("ResultCache braucht einen Ordner (root) oder einen Objektspeicher (store)")
        self.root = Path(root) if root is not None else None
        self.store = store
        self.prefix = prefix
        self.hits = 0
        self.misses = 0

    def key(self, source: str, stage: str, payload: Any, version: str) -> str:
        """Key aus Quelle, Stufe und Hash der Eingabe; ``version`` trennt inkompatible Formate."""
        stage = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(stage or "stage"))
        return storage.derived_key(
            str(source), {"stage": stage, "input_sha256": input_hash(payload)}, version, "json", prefix=f"{self.prefix}/{stage}"
        )

    def _path(self, key: str) -> Path:
        assert self.root is not None
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("Ungültiger Cache-Key")
        return p

    def get(self, key: str) -> Any:
        try:
            if self.root is not None:
                p = self._path(key)
                if not p.is_file():
                    self.misses += 1
                    return None
                value = json.loads(p.read_text(encoding="utf-8"))
            else:
                if not self.store.exists("derived", key):
                    self.misses += 1
                    return None
                value = self.store.get_json("derived", key)
        except (OSError, ValueError) as exc:
            log.warning("Ergebnis-Cache unlesbar key=%s: %s", key[:40], exc.__class__.__name__)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def put(self, key: str, value: Any) -> None:
        if self.root is not None:
            p = self._path(key)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
        else:
            self.store.put_json("derived", key, value)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


__all__ = ["ResultCache", "input_hash"]
