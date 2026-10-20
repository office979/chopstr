"""Activities ``transcribe_de`` und ``diarize`` (Task-Queue ``chopstr-gpu``).

Zwischenergebnisse landen als JSON im Derived-Bucket:
  asr/<sha256(audio_key + variant + vocab + fenster + modell)>.json
  diar/<sha256(audio_key + sprecheranzahl + modell)>.json
Beide Activities geben den Storage-Key zurück und sind idempotent.

Lane P1: Mit ``ASR_AUTO_ROUTE=1`` wählt ``asr.transcribe`` die Route nach erkannter Sprache; der Key enthält
dann den Schalter, beide Modelle, die geschützten Begriffe und die ASR-Regeln, damit ``fuse_and_nlp`` ihn
aus Quelle und Einstellungen rekonstruiert (``asr_key_for_source``). Mit ``SPEAKERS_MULTITRACK=1`` und
mindestens zwei Spuren in ``sources.audio_tracks`` kommt die Sprecherzuordnung aus der Spurenergie
(``multitrack_energy``), ohne pyannote (``diar_key_for_source``).
"""

from __future__ import annotations

import time

from temporalio import activity

from .. import costlog, db, events, storage
from ..pipeline import transcribe as asr
from . import common

STEP_ASR = "transcribe_de"
STEP_DIAR = "diarize"
ASR_PIPELINE_VERSION = "asr_v1"
DIAR_PIPELINE_VERSION = "diar_v1"


def asr_key_for(audio_key: str, variant: str, vocab: list[str], model_id: str, s, extra: dict | None = None) -> str:
    """Ohne Marken-Wörterbuch derselbe Key wie vor Lane P1. Mit Wörterbuch kommt ``hotwords: post_only`` dazu,
    solange es nicht in den Decoder geht (``asr.hotwords.decode``, Notiz 010): Transkripte, die noch mit
    Decoder-Hotwords entstanden sind und Sätze verschluckt haben können, werden so nicht wiederverwendet."""
    params = {"variant": variant, "vocab": common.vocab_hash(vocab), "window_s": s.asr_window_s, "overlap_s": s.asr_overlap_s}
    decode = asr.asr_settings()["decode"] if s.asr_auto_route else asr.ASR_DEFAULTS["decode"]
    if vocab and not decode:
        params["hotwords"] = "post_only"
    params.update(extra or {})
    return storage.derived_key(audio_key, params, f"{ASR_PIPELINE_VERSION}:{model_id}", "json", prefix="asr")


def diar_key_for(audio_key: str, expected_speakers: int | None, model_id: str, extra: dict | None = None) -> str:
    params = {"speakers": expected_speakers, **(extra or {})}
    return storage.derived_key(audio_key, params, f"{DIAR_PIPELINE_VERSION}:{model_id}", "json", prefix="diar")


def asr_model_for_source(src: dict, s, fallback: str | None = None) -> str:
    """Modell-ID für den Key: Gladia, unter ``ASR_AUTO_ROUTE`` das Erkennungsmodell (DE), sonst das Profilmodell."""
    if fallback == "gladia-eu":
        return "gladia"
    if s.asr_auto_route:
        return s.asr_model_de or s.asr_model_for(src["asr_variant"])
    return s.asr_model_for(src["asr_variant"])


def asr_key_for_source(src: dict, s, fallback: str | None = None) -> str:
    """ASR-Key aus Quelle und Einstellungen; ``run_transcribe`` und ``nlp._find_latest_key`` nutzen denselben Weg.
    Unter ``ASR_AUTO_ROUTE`` stehen Schalter, CH-Modell, geschützte Begriffe und ASR-Regeln mit im Key."""
    audio_key = common.require(src, "audio_key", "Audio-Spur")
    vocab = src["brand_vocab"]
    model_id = asr_model_for_source(src, s, fallback)
    extra: dict = {}
    if fallback != "gladia-eu" and s.asr_auto_route:
        extra.update(
            auto_route=1,
            protected=common.vocab_hash(list(src.get("protected_terms") or [])),
            model_ch=s.asr_model_ch,
            asr_rules=asr.asr_settings(),
        )
    return asr_key_for(audio_key, src["asr_variant"], vocab, model_id, s, extra)


def audio_tracks(ctx: common.Context, source_id: str) -> list[str]:
    """Spur-Keys aus ``sources.audio_tracks`` (Migration 0018); ohne ``SPEAKERS_MULTITRACK`` leer, ohne Abfrage."""
    if not ctx.settings.speakers_multitrack:
        return []
    row = db.fetch_one(ctx.conn, "select audio_tracks from sources where id = %s", (source_id,))
    raw = row[0] if row else None
    if isinstance(raw, str):
        import json

        raw = json.loads(raw)
    return [str(k) for k in (raw or []) if k]


def diar_key_for_source(ctx: common.Context, src: dict, s) -> tuple[str, str, list[str]]:
    """``(key, model_id, tracks)`` der Sprecherzuordnung; mit zwei oder mehr Spuren ``multitrack_energy``."""
    audio_key = common.require(src, "audio_key", "Audio-Spur")
    tracks = audio_tracks(ctx, src["id"])
    if len(tracks) >= 2:
        extra = {"tracks": tracks, "rules": asr.speaker_settings()}
        return diar_key_for(audio_key, src.get("expected_speakers"), asr.DIARIZER_MULTITRACK, extra), asr.DIARIZER_MULTITRACK, tracks
    model_id = asr.diarizer_id(s)
    return diar_key_for(audio_key, src.get("expected_speakers"), model_id), model_id, []


def _gpu_or_cpu_seconds(seconds: float, s) -> dict:
    device = (s.asr_device or "auto").lower()
    if device == "cuda":
        return {"gpu_seconds": seconds}
    if device == "cpu":
        return {"cpu_seconds": seconds}
    try:
        import torch

        return {"gpu_seconds": seconds} if torch.cuda.is_available() else {"cpu_seconds": seconds}
    except ImportError:
        return {"cpu_seconds": seconds}


def run_transcribe(ctx: common.Context, source_id: str, fallback: str | None = None) -> str:
    src = db.load_source(ctx.conn, source_id)
    s = ctx.settings
    variant = src["asr_variant"]
    vocab = src["brand_vocab"]
    model_id = asr_model_for_source(src, s, fallback)
    with events.step(ctx.conn, source_id, STEP_ASR, f"Transkription ({variant}) startet") as st:
        audio_key = common.require(src, "audio_key", "Audio-Spur")
        if not model_id:
            env = "ASR_MODEL_CH" if variant == "de-CH" else "ASR_MODEL_DE"
            raise asr.TranscribeError(f"Kein ASR-Modell für Variante {variant} konfiguriert ({env} setzen)")
        key = asr_key_for_source(src, s, fallback)
        if ctx.store.exists("derived", key):
            st.finish("Transkript bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
            return key
        local = common.ensure_local_audio(ctx, source_id, audio_key)
        common.heartbeat("audio ready")
        st.progress(0.1, "Modell geladen, Transkription läuft")
        t0 = time.monotonic()
        result = asr.transcribe(
            str(local), variant=variant, brand_vocab=vocab, s=s, fallback=fallback, duration_s=src.get("duration_s"),
            protected_terms=src.get("protected_terms") or [],
        )  # fmt: skip
        elapsed = time.monotonic() - t0
        common.heartbeat("transcribed")
        payload = result.to_dict()
        payload["source_id"] = source_id
        ctx.store.put_json("derived", key, payload)
        costlog.record(
            ctx.conn,
            costlog.Cost(
                workspace_id=src["workspace_id"],
                source_id=source_id,
                job_type="asr",
                provider=result.provider,
                model_id=result.model_id,
                source_minutes=result.duration_s / 60.0,
                **_gpu_or_cpu_seconds(elapsed, s),
            ),
            s,
        )
        hint = None if result.provider == "gladia-eu" else asr.model_hint(result.model_id)
        st.finish(
            f"{result.stats.get('word_count', 0)} Wörter in {result.windows} Fenstern"
            + (" (Schweizerdeutsch, Beta)" if result.beta else "")
            + (f" ({hint})" if hint else ""),
            key=key,
            word_count=result.stats.get("word_count", 0),
            low_conf_ratio=result.stats.get("low_conf_ratio", 0.0),
            windows=result.windows,
            beta=result.beta,
            model_id=result.model_id,
            hint=hint,
            routing_reason=result.route.get("routing_reason"),
            detected_variant=result.route.get("detected_variant"),
            verbatim=result.route.get("verbatim"),
            route_hints=result.route.get("hints") or [],
        )
    return key


def run_diarize(ctx: common.Context, source_id: str) -> str:
    """Sprechererkennung; ohne ``HF_TOKEN`` oder pyannote läuft der Fallback (ein Sprecher) mit Hinweis im Event."""
    src = db.load_source(ctx.conn, source_id)
    s = ctx.settings
    n = src.get("expected_speakers")
    with events.step(ctx.conn, source_id, STEP_DIAR, "Sprechererkennung startet") as st:
        audio_key = common.require(src, "audio_key", "Audio-Spur")
        key, model_id, tracks = diar_key_for_source(ctx, src, s)
        if ctx.store.exists("derived", key):
            st.finish("Sprecherzuordnung bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
            return key
        if tracks:
            paths = []
            for k, tkey in enumerate(tracks):
                local_t = ctx.source_dir(source_id) / f"track{k}.wav"
                if not local_t.is_file():
                    ctx.store.download_to("derived", tkey, local_t)
                paths.append(str(local_t))
            result = asr.multitrack_diarization(paths, asr.speaker_settings())
            result["source_id"] = source_id
            ctx.store.put_json("derived", key, result)
            st.finish(
                f"{len(result['speakers'])} Sprecher aus {len(tracks)} Spuren, {len(result['turns'])} Abschnitte",
                key=key, speakers=len(result["speakers"]), diarization="multitrack_energy", tracks=len(tracks),
            )  # fmt: skip
            return key
        local = common.ensure_local_audio(ctx, source_id, audio_key)
        common.heartbeat("audio ready")
        result = asr.diarize(str(local), min_speakers=n, max_speakers=n, s=s)
        common.heartbeat("diarized")
        result["source_id"] = source_id
        ctx.store.put_json("derived", key, result)
        if result.get("skipped"):
            hints = [str(result.get("hint") or asr.HINT_DIARIZATION_SKIPPED)]
            if n and int(n) > 1:
                hints.append(f"Quelle erwartet {int(n)} Sprecher, alle Wörter werden {asr.FALLBACK_SPEAKER} zugeordnet")
            st.finish(
                "; ".join(hints), key=key, speakers=1, diarization="skipped", hint=hints[0], hints=hints,
            )  # fmt: skip
            return key
        costlog.record(
            ctx.conn,
            costlog.Cost(
                workspace_id=src["workspace_id"],
                source_id=source_id,
                job_type="diarize",
                provider="selfhost-eu",
                model_id=result["model_id"],
                source_minutes=float(src.get("duration_s") or 0.0) / 60.0,
                **_gpu_or_cpu_seconds(result["compute_seconds"], s),
            ),
            s,
        )
        st.finish(
            f"{len(result['speakers'])} Sprecher, {len(result['turns'])} Abschnitte",
            key=key, speakers=len(result["speakers"]), diarization="done",
        )  # fmt: skip
    return key


@activity.defn(name="transcribe_de")
def transcribe_de(source_id: str) -> str:
    ctx = common.open_context()
    try:
        return run_transcribe(ctx, source_id)
    finally:
        ctx.close()


@activity.defn(name="diarize")
def diarize(source_id: str) -> str:
    ctx = common.open_context()
    try:
        return run_diarize(ctx, source_id)
    finally:
        ctx.close()


__all__ = [
    "STEP_ASR", "STEP_DIAR", "asr_key_for", "asr_key_for_source", "asr_model_for_source", "audio_tracks",
    "diar_key_for", "diar_key_for_source", "diarize", "run_diarize", "run_transcribe", "transcribe_de",
]  # fmt: skip
