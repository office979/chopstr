"""Activities ``heatmap``, ``detect_candidates`` (Phase 1: skipped), ``render_pack`` (Stub), ``notify``.

``heatmap`` läuft parallel zur Transkription und nutzt deshalb primär das Audio-Signal. Liegt das
ASR-Ergebnis bereits im Storage (Re-Run), fließt auch der Text-Anteil ein (``signals.combined``).
"""

from __future__ import annotations

import logging
import time

from temporalio import activity

from .. import costlog, db, events, storage
from ..pipeline import signals
from . import common
from .transcribe import asr_key_for

log = logging.getLogger("chopstr.activities.analyze")

STEP_HEATMAP = "heatmap"
STEP_CANDIDATES = "detect_candidates"
STEP_RENDER = "render"
SIGNALS_VERSION = "signals_v1"


def heatmap_key_for(audio_key: str, with_text: bool) -> str:
    return storage.derived_key(audio_key, {"text": with_text}, SIGNALS_VERSION, "json", prefix="heatmap")


def run_heatmap(ctx: common.Context, source_id: str) -> str:
    src = db.load_source(ctx.conn, source_id)
    s = ctx.settings
    t0 = time.monotonic()
    with events.step(ctx.conn, source_id, STEP_HEATMAP, "Signal-Heatmap wird berechnet", fail_status=None) as st:
        audio_key = common.require(src, "audio_key", "Audio-Spur")
        words: list[dict] = []
        model_id = s.asr_model_for(src["asr_variant"])
        if model_id:
            akey = asr_key_for(audio_key, src["asr_variant"], src["brand_vocab"], model_id, s)
            if ctx.store.exists("derived", akey):
                words = ctx.store.get_json("derived", akey).get("words", [])
        key = heatmap_key_for(audio_key, bool(words))
        if ctx.store.exists("derived", key):
            st.finish("Heatmap bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
            return key
        local = common.ensure_local_audio(ctx, source_id, audio_key)
        heat = signals.combined(str(local), words)
        payload = signals.to_payload(heat)
        payload["source_id"] = source_id
        payload["text_included"] = bool(words)
        ctx.store.put_json("derived", key, payload)
        costlog.record(
            ctx.conn,
            costlog.Cost(
                workspace_id=src["workspace_id"],
                source_id=source_id,
                job_type="heatmap",
                provider="selfhost-eu",
                source_minutes=float(src.get("duration_s") or 0.0) / 60.0,
                cpu_seconds=time.monotonic() - t0,
            ),
            s,
        )
        st.finish(f"{payload['n_bins']} Sekunden analysiert, {len(payload['seeds'])} Seeds", key=key, seeds=len(payload["seeds"]))
    return key


def run_detect_candidates(ctx: common.Context, source_id: str) -> list[str]:
    """Phase 1: nur ein 'skipped'-Event. Die Story-Engine (story_score, story_graph) folgt in Phase 2."""
    events.emit(ctx.conn, source_id, STEP_CANDIDATES, "skipped", "Kandidaten kommen in Phase 2")
    return []


@activity.defn(name="heatmap")
def heatmap(source_id: str) -> str:
    ctx = common.open_context()
    try:
        return run_heatmap(ctx, source_id)
    finally:
        ctx.close()


@activity.defn(name="detect_candidates")
def detect_candidates(source_id: str) -> list[str]:
    ctx = common.open_context()
    try:
        return run_detect_candidates(ctx, source_id)
    finally:
        ctx.close()


@activity.defn(name="render_pack")
def render_pack(candidate_id: str, destination: str) -> str:
    """Phase 3: compose, reframe, captions, render, C2PA. Aktuell Stub."""
    raise NotImplementedError("Rendern kommt in Phase 3")


@activity.defn(name="notify")
def notify(source_id: str, event: str) -> None:
    """Benachrichtigung an die UI: aktuell ein pipeline_event, das die UI per Polling/SSE liest."""
    ctx = common.open_context()
    try:
        events.emit(ctx.conn, source_id, "notify", "finished", event, payload={"event": event})
    finally:
        ctx.close()


__all__ = [
    "SIGNALS_VERSION",
    "STEP_CANDIDATES",
    "STEP_HEATMAP",
    "STEP_RENDER",
    "detect_candidates",
    "heatmap",
    "heatmap_key_for",
    "notify",
    "render_pack",
    "run_detect_candidates",
    "run_heatmap",
]
