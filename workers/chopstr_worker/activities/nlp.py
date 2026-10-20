"""Activity ``fuse_and_nlp``: Wörter und Sprecher fusionieren, DACH-NLP annotieren, Transkriptversion schreiben.

Ablauf: ASR-JSON + Diarisierungs-JSON aus dem Storage laden, ``assign_speakers`` (Mehrheit über
Wortdauer), DANACH ``normalize_numbers`` (Zahlen erst nach dem Alignment), ``dach_nlp.annotate``
(filler, negation, sentence_idx), Statistik, ``transcript_versions`` (version = max+1, origin 'asr').
Der Status bleibt ``analyzing``; Phase 2 (``detect_candidates``) setzt ``scoring`` und am Ende ``ready``.

Schweizerdeutsch-Beta (Phase 5c): ``dach_nlp.detect_dialect`` schreibt ``stats.dialect``; bei erkanntem CH
oder ``asr_variant = de-CH`` bekommen Wörter mit sicherer Entsprechung ``text_norm`` (Original bleibt ``text``,
``protected_terms`` des Markenprofils werden nie normalisiert). Ist CH erkannt, aber die Quelle läuft mit dem
DE-Modell, steht der Hinweis im Event (``hint``), damit der Editor das CH-Modell empfehlen kann.

Lane P1: ``stats.asr_route`` ist der Datenvertrag der ASR-Route (Regel 13: Variante, Modell, ``verbatim``,
``time_source``, Erkennung, Grund); ``text`` bleibt die gesprochene Form, ``text_norm`` nur Untertitelform.
Bringt die Sprecherzuordnung ``overlap_turns`` mit (pyannote regulär oder Spurenergie), tragen Wörter in
Überlappung ``overlap`` und ``speakers``, und ``stats.overlap_ratio`` nennt den Anteil. ``stats.diarization``
ist ``skipped``, ``done`` oder ``multitrack_energy``; ``transcript_versions.diarizer_id`` ist dann ``none``,
das Modell oder ``multitrack_energy``.
"""

from __future__ import annotations

import time

from temporalio import activity

from .. import costlog, db, editorial, events
from ..pipeline import dach_nlp
from ..pipeline import transcribe as asr
from . import common
from .transcribe import asr_key_for_source, diar_key_for_source

STEP = "fuse_and_nlp"
HINT_CH_MODEL = "Schweizerdeutsch erkannt, CH-Modell empfohlen (Beta)"


def _find_latest_key(ctx: common.Context, src: dict, kind: str) -> str:
    """Rekonstruiert den deterministischen Key aus den aktuellen Einstellungen."""
    s = ctx.settings
    common.require(src, "audio_key", "Audio-Spur")
    if kind == "asr":
        key = asr_key_for_source(src, s)
    else:
        key = diar_key_for_source(ctx, src, s)[0]
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
        raw_overlap = diar_doc.get("overlap_turns")
        overlap_turns = [(float(t[0]), float(t[1]), str(t[2])) for t in raw_overlap] if raw_overlap is not None else None
        min_ratio = asr.speaker_settings()["overlap_min_ratio"] if overlap_turns is not None else asr.SPEAKER_DEFAULTS["overlap_min_ratio"]

        asr.assign_speakers(words, turns, overlap_turns, min_ratio)
        asr.normalize_numbers(words)  # erst nach dem Alignment
        dialect = dach_nlp.detect_dialect(words)
        asr_variant = str(asr_doc.get("variant") or src.get("asr_variant") or "de")
        ch = dialect["variant"] == "de-CH" or asr_variant == "de-CH"
        # Satzende-Regel aus der aktiven Richtlinie (AP2): v1 wie bisher, v2 nur mit implementation.sentence_rule.
        # Unter v2 mit kaum Satzzeichen gilt v1 (``v1_fallback_no_punct``, steht so in stats).
        policy = editorial.load()
        sentence_rule = dach_nlp.resolve_sentence_rule(words, editorial.sentence_rule(policy))
        max_s, max_words = editorial.sentence_limits(policy)
        dach_nlp.annotate(
            words,
            protected_terms=src.get("protected_terms") or [],
            dialect="de-CH" if ch else None,
            rule=sentence_rule,
            max_s=max_s,
            max_words=max_words,
        )
        common.heartbeat("annotated")

        stats = asr.confidence_stats(words)
        stats["sentence_count"] = (words[-1]["sentence_idx"] + 1) if words else 0
        stats["filler_hard"] = sum(1 for w in words if w.get("filler") == "hard")
        stats["negations"] = sum(1 for w in words if w.get("negation"))
        stats["beta"] = bool(asr_doc.get("beta"))
        stats["verb_bracket_available"] = dach_nlp.verb_bracket_available
        stats["sentence_rule"] = sentence_rule
        stats["dialect"] = {"variant": dialect["variant"], "confidence": dialect["confidence"], "markers": dialect["markers"]}
        stats["text_norm_count"] = sum(1 for w in words if w.get("text_norm"))
        stats["diarization"] = "skipped" if diar_doc.get("skipped") else ("multitrack_energy" if diar_doc.get("model_id") == asr.DIARIZER_MULTITRACK else "done")
        route = asr_doc.get("route") or asr.default_route(asr_variant, str(asr_doc.get("model_id") or ""), bool(asr_doc.get("beta")), str(asr_doc.get("provider") or ""))
        stats["asr_route"] = {k: route.get(k) for k in ("variant", "model_id", "verbatim", "time_source", "beta", "detected_language", "detected_variant", "routing_reason", "hints")}
        if overlap_turns is not None:
            stats["overlap_ratio"] = asr.overlap_ratio(words) or 0.0
        hint = HINT_CH_MODEL if dialect["variant"] == "de-CH" and asr_variant != "de-CH" else None

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
            f"Transkript Version {version}: {stats['word_count']} Wörter, {stats['sentence_count']} Sätze, {len(stats['speakers'])} Sprecher"
            + (f" ({hint})" if hint else ""),
            transcript_version=version,
            transcript_version_id=tv_id,
            word_count=stats["word_count"],
            low_conf_ratio=stats["low_conf_ratio"],
            dialect=stats["dialect"],
            text_norm_count=stats["text_norm_count"],
            hint=hint,
        )
    return tv_id


@activity.defn(name="fuse_and_nlp")
def fuse_and_nlp(source_id: str) -> str:
    ctx = common.open_context()
    try:
        return run(ctx, source_id)
    finally:
        ctx.close()


__all__ = ["HINT_CH_MODEL", "STEP", "fuse_and_nlp", "run"]
