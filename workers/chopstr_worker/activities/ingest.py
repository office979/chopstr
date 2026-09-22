"""Activity ``probe_and_extract``: Original laden, ffprobe, sha256, 16-kHz-WAV, 720p-Proxy.

Schreibt ``sources`` (sha256, duration_s, width, height, fps, audio_key, proxy_key, size_bytes),
Status ``ingesting`` zu ``transcribing``, Events und ``job_costs`` (ingest).
Idempotent: vorhandene Ableitungen im Storage werden übersprungen.
"""

from __future__ import annotations

import time

from temporalio import activity

from .. import costlog, db, events, ingest
from . import common

STEP = "probe_and_extract"


def run(ctx: common.Context, source_id: str) -> dict:
    src = db.load_source(ctx.conn, source_id)
    t0 = time.monotonic()
    with events.step(ctx.conn, source_id, STEP, "Datei wird geprüft und Audio extrahiert") as st:
        events.set_source_status(ctx.conn, source_id, "ingesting", None)
        work = ctx.source_dir(source_id)
        original = work / "original"
        if not original.is_file():
            ctx.store.download_to("sources", src["storage_key"], original)
        common.heartbeat("downloaded")

        info = ingest.probe(original)
        if not info.has_audio:
            raise ingest.IngestError("Die Datei enthält keine Tonspur")
        st.progress(0.2, "Metadaten gelesen")
        sha = src.get("sha256") or ingest.sha256_file(original)
        common.heartbeat("hashed")
        st.progress(0.4, "Prüfsumme berechnet")

        audio_key = common.audio_key_for(src["storage_key"])
        local_wav = work / "audio16k.wav"
        if ctx.store.exists("derived", audio_key):
            if not local_wav.is_file():
                ctx.store.download_to("derived", audio_key, local_wav)
            audio_skipped = True
        else:
            ingest.extract_audio(original, local_wav)
            ctx.store.put_file("derived", audio_key, local_wav, "audio/wav")
            audio_skipped = False
        common.heartbeat("audio")
        st.progress(0.7, "Audio extrahiert")

        proxy_key = None
        proxy_skipped = False
        if info.has_video:
            proxy_key = common.proxy_key_for(src["storage_key"])
            local_proxy = work / "proxy720.mp4"
            if ctx.store.exists("derived", proxy_key):
                proxy_skipped = True
            else:
                ingest.make_proxy(original, local_proxy)
                ctx.store.put_file("derived", proxy_key, local_proxy, "video/mp4")
        common.heartbeat("proxy")

        db.update(
            ctx.conn,
            "sources",
            {"id": source_id},
            sha256=sha,
            duration_s=info.duration_s,
            width=info.width,
            height=info.height,
            fps=info.fps,
            audio_key=audio_key,
            proxy_key=proxy_key,
            size_bytes=info.size_bytes,
            mime_type=src.get("mime_type") or (f"video/{info.format_name.split(',')[0]}" if info.format_name and info.has_video else None),
        )
        events.set_source_status(ctx.conn, source_id, "transcribing", None)

        cpu_s = time.monotonic() - t0
        storage_bytes = ctx.store.size("derived", audio_key) + (ctx.store.size("derived", proxy_key) if proxy_key else 0)
        costlog.record(
            ctx.conn,
            costlog.Cost(
                workspace_id=src["workspace_id"],
                source_id=source_id,
                job_type="ingest",
                provider="selfhost-eu",
                source_minutes=info.duration_s / 60.0,
                cpu_seconds=cpu_s,
                storage_bytes=storage_bytes,
            ),
            ctx.settings,
        )
        st.finish(
            f"Dauer {info.duration_s:.0f} s, {info.width or 0}x{info.height or 0}, Audio und Proxy bereit",
            duration_s=info.duration_s,
            width=info.width,
            height=info.height,
            fps=info.fps,
            audio_skipped=audio_skipped,
            proxy_skipped=proxy_skipped,
        )
    return {
        "source_id": source_id,
        "sha256": sha,
        "duration_s": info.duration_s,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "audio_key": audio_key,
        "proxy_key": proxy_key,
    }


@activity.defn(name="probe_and_extract")
def probe_and_extract(source_id: str) -> dict:
    ctx = common.open_context()
    try:
        return run(ctx, source_id)
    finally:
        ctx.close()


__all__ = ["STEP", "probe_and_extract", "run"]
