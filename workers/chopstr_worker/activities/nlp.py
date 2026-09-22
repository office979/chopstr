"""Activity ``fuse_and_nlp``: Wörter und Sprecher fusionieren, DACH-NLP annotieren, Transkriptversion schreiben.

Ablauf: ASR-JSON + Diarisierungs-JSON aus dem Storage laden, ``assign_speakers`` (Mehrheit über
Wortdauer), DANACH ``normalize_numbers`` (Zahlen erst nach dem Alignment), ``dach_nlp.annotate``
(filler, negation, sentence_idx), Statistik, ``transcript_versions`` (version = max+1, origin 'asr').
Der Status bleibt ``analyzing``; Phase 2 (``detect_candidates``) setzt ``scoring`` und am Ende ``ready``.
"""

from __future__ import annotations

import time

from temporalio import activity

from .. import costlog, db, events
from ..pipeline import dach_nlp
from ..pipeline import transcribe as asr
from . import common
from .transcribe import asr_key_for, diar_key_for

STEP = "fuse_and_nlp"


def _find_latest_key(ctx: common.Context, src: dict, kind: str) -> str:
    """Rekonstruiert den deterministischen Key aus den aktuellen Einstellungen."""
    s = ctx.settings
    audio_key = common.require(src, "audio_key", "Audio-Spur")
    if kind == "asr":
        model_id = s.asr_model_for(src["asr_variant"])
        key = asr_key_for(audio_key, src["asr_variant"], src["brand_vocab"], model_id, s)
    else:
        key = diar_key_for(audio_key, src.get("expected_speakers"), s.diarizer_model or asr._DEFAULT_DIARIZER)
    if not ctx.store.exists("derived", key):
        what = "Transkript" if kind == "asr" else "Sprecherzuordnung"
        raise RuntimeError(f"{what} nicht im Speicher gefunden (Key {key[:24]}...)")
    return key


def run(ctx: common.Context, source_id: str, asr_key: str | None = None, diar_key: str | None = None) -> str:
    src = db.load_source(ctx.conn, source_id)
    t0 = time.monotonic()
    with events.step(ctx.conn, source_id, STEP, "Transkript und Sprecher werden zusammengeführt") as st:
        events.set_source_status(ctx.conn, source_id, "analyzing", None)
        asr_key = asr_key or _find_latest_key(ctx, src, "asr")
        diar_key = diar_key or _find_latest_key(ctx, src, "diar")
        asr_doc = ctx.store.get_json("derived", asr_key)
        diar_doc = ctx.store.get_json("derived", diar_key)
        words = [dict(w) for w in asr_doc["words"]]
        turns = [(float(t[0]), float(t[1]), str(t[2])) for t in diar_doc.get("turns", [])]

        asr.assign_speakers(words, turns)
        asr.normalize_numbers(words)  # erst nach dem Alignment
        dach_nlp.annotate(words)
        common.heartbeat("annotated")

        stats = asr.confidence_stats(words)
        stats["sentence_count"] = (words[-1]["sentence_idx"] + 1) if words else 0
        stats["filler_hard"] = sum(1 for w in words if w.get("filler") == "hard")
        stats["negations"] = sum(1 for w in words if w.get("negation"))
        stats["beta"] = bool(asr_doc.get("beta"))
        stats["verb_bracket_available"] = dach_nlp.verb_bracket_available

        row = db.fetch_one(ctx.conn, "select coalesce(max(version), 0) from transcript_versions where source_id = %s", (source_id,))
        version = int(row[0] if row else 0) + 1
        inserted = db.insert(
            ctx.conn,
            "transcript_versions",
            returning="id",
            source_id=source_id,
            version=version,
            origin="asr",
            asr_model_id=asr_doc.get("model_id"),
            asr_variant=asr_doc.get("variant"),
            diarizer_id=diar_doc.get("model_id"),
            language="de",
            words=db.jsonb(words),
            stats=db.jsonb(stats),
        )
        tv_id = str(inserted[0]) if inserted else f"{source_id}:{version}"
        costlog.record(
            ctx.conn,
            costlog.Cost(
                workspace_id=src["workspace_id"],
                source_id=source_id,
                job_type="nlp",
                provider="selfhost-eu",
                source_minutes=float(src.get("duration_s") or 0.0) / 60.0,
                cpu_seconds=time.monotonic() - t0,
            ),
            ctx.settings,
        )
        st.finish(
            f"Transkript Version {version}: {stats['word_count']} Wörter, {stats['sentence_count']} Sätze, {len(stats['speakers'])} Sprecher",
            transcript_version=version,
            transcript_version_id=tv_id,
            word_count=stats["word_count"],
            low_conf_ratio=stats["low_conf_ratio"],
        )
    return tv_id


@activity.defn(name="fuse_and_nlp")
def fuse_and_nlp(source_id: str) -> str:
    ctx = common.open_context()
    try:
        return run(ctx, source_id)
    finally:
        ctx.close()


__all__ = ["STEP", "fuse_and_nlp", "run"]
