"""Temporal-Activities: dünne Hüllen um die Pipeline-Module mit DB, Storage, Events und Kostenlog.

Alle Activities sind synchron (blockierende I/O) und laufen im Worker über einen ThreadPoolExecutor.
Sie sind idempotent: Output-Keys werden aus sha256(asset + Parameter + Modellversion) gebildet und
vorhandene Outputs übersprungen.
"""

from __future__ import annotations

from .analyze import detect_candidates, heatmap, notify
from .deletion import delete_entity, enqueue_deletion, find_expired
from .ingest import probe_and_extract
from .nlp import fuse_and_nlp
from .render import render_pack
from .transcribe import diarize, transcribe_de

CPU_ACTIVITIES = [
    probe_and_extract, heatmap, fuse_and_nlp, detect_candidates, render_pack, notify,
    delete_entity, find_expired, enqueue_deletion,
]  # fmt: skip
GPU_ACTIVITIES = [transcribe_de, diarize]
ALL_ACTIVITIES = CPU_ACTIVITIES + GPU_ACTIVITIES

__all__ = [
    "ALL_ACTIVITIES",
    "CPU_ACTIVITIES",
    "GPU_ACTIVITIES",
    "delete_entity",
    "detect_candidates",
    "diarize",
    "enqueue_deletion",
    "find_expired",
    "fuse_and_nlp",
    "heatmap",
    "notify",
    "probe_and_extract",
    "render_pack",
    "transcribe_de",
]
