"""Temporal-Activities: dünne Hüllen um die Pipeline-Module mit DB, Storage, Events und Kostenlog.

Alle Activities sind synchron (blockierende I/O) und laufen im Worker über einen ThreadPoolExecutor.
Sie sind idempotent: Output-Keys werden aus sha256(asset + Parameter + Modellversion) gebildet und
vorhandene Outputs übersprungen.
"""

from __future__ import annotations

from .analyze import detect_candidates, heatmap, notify, render_pack
from .ingest import probe_and_extract
from .nlp import fuse_and_nlp
from .transcribe import diarize, transcribe_de

CPU_ACTIVITIES = [probe_and_extract, heatmap, fuse_and_nlp, detect_candidates, render_pack, notify]
GPU_ACTIVITIES = [transcribe_de, diarize]
ALL_ACTIVITIES = CPU_ACTIVITIES + GPU_ACTIVITIES

__all__ = [
    "ALL_ACTIVITIES",
    "CPU_ACTIVITIES",
    "GPU_ACTIVITIES",
    "detect_candidates",
    "diarize",
    "fuse_and_nlp",
    "heatmap",
    "notify",
    "probe_and_extract",
    "render_pack",
    "transcribe_de",
]
