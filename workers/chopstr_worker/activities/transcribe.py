"""Activities ``transcribe_de`` und ``diarize`` (Task-Queue ``chopstr-gpu``).

Zwischenergebnisse landen als JSON im Derived-Bucket:
  asr/<sha256(audio_key + variant + vocab + fenster + modell)>.json
  diar/<sha256(audio_key + sprecheranzahl + modell)>.json
Beide Activities geben den Storage-Key zurück und sind idempotent.
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


def asr_key_for(audio_key: str, variant: str, vocab: list[str], model_id: str, s) -> str:
    params = {"variant": variant, "vocab": common.vocab_hash(vocab), "window_s": s.asr_window_s, "overlap_s": s.asr_overlap_s}
    return storage.derived_key(audio_key, params, f"{ASR_PIPELINE_VERSION}:{model_id}", "json", prefix="asr")


def diar_key_for(audio_key: str, expected_speakers: int | None, model_id: str) -> str:
    return storage.derived_key(audio_key, {"speakers": expected_speakers}, f"{DIAR_PIPELINE_VERSION}:{model_id}", "json", prefix="diar")


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
    model_id = "gladia" if fallback == "gladia-eu" else s.asr_model_for(variant)
    with events.step(ctx.conn, source_id, STEP_ASR, f"Transkription ({variant}) startet") as st:
        audio_key = common.require(src, "audio_key", "Audio-Spur")
        if not model_id:
            env = "ASR_MODEL_CH" if variant == "de-CH" else "ASR_MODEL_DE"
            raise asr.TranscribeError(f"Kein ASR-Modell für Variante {variant} konfiguriert ({env} setzen)")
        key = asr_key_for(audio_key, variant, vocab, model_id, s)
        if ctx.store.exists("derived", key):
            st.finish("Transkript bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
            return key
        local = common.ensure_local_audio(ctx, source_id, audio_key)
        common.heartbeat("audio ready")
        st.progress(0.1, "Modell geladen, Transkription läuft")
        t0 = time.monotonic()
        result = asr.transcribe(str(local), variant=variant, brand_vocab=vocab, s=s, fallback=fallback, duration_s=src.get("duration_s"))
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
        )
    return key


def run_diarize(ctx: common.Context, source_id: str) -> str:
    """Sprechererkennung; ohne ``HF_TOKEN`` oder pyannote läuft der Fallback (ein Sprecher) mit Hinweis im Event."""
    src = db.load_source(ctx.conn, source_id)
    s = ctx.settings
    n = src.get("expected_speakers")
    model_id = asr.diarizer_id(s)
    with events.step(ctx.conn, source_id, STEP_DIAR, "Sprechererkennung startet") as st:
        audio_key = common.require(src, "audio_key", "Audio-Spur")
        key = diar_key_for(audio_key, n, model_id)
        if ctx.store.exists("derived", key):
            st.finish("Sprecherzuordnung bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
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


__all__ = ["STEP_ASR", "STEP_DIAR", "asr_key_for", "diar_key_for", "diarize", "run_diarize", "run_transcribe", "transcribe_de"]
