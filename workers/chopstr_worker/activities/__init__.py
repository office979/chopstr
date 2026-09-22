"""Temporal-Activities: dünne Hüllen um die Pipeline-Module mit DB, Storage, Events und Kostenlog.

Alle Activities sind synchron (blockierende I/O) und laufen im Worker über einen ThreadPoolExecutor.
Sie sind idempotent: Output-Keys werden aus sha256(asset + Parameter + Modellversion) gebildet und
vorhandene Outputs übersprungen.
"""

from __future__ import annotations

from .analyze import detect_candidates, heatmap, notify
from .deletion import delete_entity, enqueue_deletion, find_expired
from .ingest import probe_and_extract
from .learning import find_learning_profiles, learn_brand_profile
from .nlp import fuse_and_nlp
from .publish import cancel_publication, fetch_metrics, load_publication_activity, publish_clip
from .render import render_pack
from .reports import build_weekly_report, find_report_workspaces
from .transcribe import diarize, transcribe_de
from .webhooks import deliver_webhook, dispatch_outbox, find_due_deliveries

CPU_ACTIVITIES = [
    probe_and_extract, heatmap, fuse_and_nlp, detect_candidates, render_pack, notify,
    delete_entity, find_expired, enqueue_deletion,
    # Phase 5
    dispatch_outbox, find_due_deliveries, deliver_webhook,
    load_publication_activity, publish_clip, fetch_metrics, cancel_publication,
    find_learning_profiles, learn_brand_profile,
    find_report_workspaces, build_weekly_report,
]  # fmt: skip
GPU_ACTIVITIES = [transcribe_de, diarize]
ALL_ACTIVITIES = CPU_ACTIVITIES + GPU_ACTIVITIES

__all__ = [
    "ALL_ACTIVITIES",
    "CPU_ACTIVITIES",
    "GPU_ACTIVITIES",
    "build_weekly_report",
    "cancel_publication",
    "delete_entity",
    "deliver_webhook",
    "detect_candidates",
    "diarize",
    "dispatch_outbox",
    "enqueue_deletion",
    "fetch_metrics",
    "find_due_deliveries",
    "find_expired",
    "find_learning_profiles",
    "find_report_workspaces",
    "fuse_and_nlp",
    "heatmap",
    "learn_brand_profile",
    "load_publication_activity",
    "notify",
    "probe_and_extract",
    "publish_clip",
    "render_pack",
    "transcribe_de",
]
