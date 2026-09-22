"""Activities ``heatmap``, ``detect_candidates`` (Phase 2: Story-Engine), ``notify``; ``render_pack`` (Phase 3)
kommt aus ``activities.render`` und wird hier nur re-exportiert.

``heatmap`` läuft parallel zur Transkription und nutzt deshalb primär das Audio-Signal. Liegt das
ASR-Ergebnis bereits im Storage (Re-Run), fließt auch der Text-Anteil ein (``signals.combined``).
``detect_candidates`` lädt Transkript, Briefing, Markenprofil und Heatmap, lässt ``pipeline.story_engine``
laufen und schreibt ``candidates`` nach ``packages/schema/CANDIDATES.md``.
"""

from __future__ import annotations

import logging
import time

from temporalio import activity

from .. import costlog, db, events, storage, usage
from ..pipeline import signals, story_engine
from ..providers_llm import LLM
from ..residency import Tenant
from . import common
from .render import STEP_RENDER, render_pack
from .transcribe import asr_key_for

log = logging.getLogger("chopstr.activities.analyze")

STEP_HEATMAP = "heatmap"
STEP_CANDIDATES = "detect_candidates"
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


def _load_heat(ctx: common.Context, src: dict) -> dict | None:
    """Heatmap-JSON aus dem Storage (mit oder ohne Textanteil); fehlt sie, läuft die Engine ohne Seeds."""
    audio_key = src.get("audio_key")
    if not audio_key:
        return None
    for with_text in (True, False):
        key = heatmap_key_for(audio_key, with_text)
        if ctx.store.exists("derived", key):
            return ctx.store.get_json("derived", key)
    return None


def candidates_key_for(tv_id: str, tv_version: int, brief: dict, prompt_versions: list[str], provider: str, model: str, weights: dict) -> str:
    """Idempotenz-Key: Transkriptversion + Briefing + Prompt-Versionen + Provider/Modell + Gewichte."""
    params = {
        "transcript_version": tv_version,
        "brief": brief,
        "prompt_versions": prompt_versions,
        "provider": provider,
        "model": model,
        "weights": weights,
        "engine": story_engine.ENGINE_VERSION,
    }
    return storage.derived_key(f"transcript/{tv_id}", params, story_engine.CONTRACT, "json", prefix="candidates")


def _write_rows(ctx: common.Context, source_id: str, cands: list[story_engine.CandidateResult]) -> list[str]:
    """Alte Kandidaten ohne Urteil löschen (Re-Run), neue Zeilen schreiben; Zeilen mit Urteil bleiben."""
    ctx.conn.execute("delete from candidates where source_id = %s and human_verdict is null", (source_id,))
    ids = []
    for c in cands:
        row = c.to_row()
        inserted = db.insert(
            ctx.conn,
            "candidates",
            returning="id",
            source_id=source_id,
            version=1,
            segments=db.jsonb(row["segments"]),
            start_s=row["start_s"],
            end_s=row["end_s"],
            first_sent=row["first_sent"],
            last_sent=row["last_sent"],
            structure=row["structure"],
            rubric=db.jsonb(row["rubric"]),
            gates=db.jsonb(row["gates"]),
            story_graph_flags=db.jsonb(row["story_graph_flags"]),
            risk_flags=db.jsonb(row["risk_flags"]),
            total=row["total"],
            gate_passed=row["gate_passed"],
            why=row["why"],
            model_id=row["model_id"],
            prompt_version=row["prompt_version"],
        )
        ids.append(str(inserted[0]) if inserted else "")
    return ids


def run_detect_candidates(ctx: common.Context, source_id: str) -> list[str]:
    """Phase 2: Story-Engine über das aktuelle Transkript, Zeilen in ``candidates`` nach Vertrag candidates_v1.

    Status ``scoring`` am Anfang, ``ready`` am Ende, ``failed`` bei Residency- oder Modellfehlern.
    Idempotent über einen Storage-Key aus Transkriptversion, Briefing, Prompt-Versionen und Provider/Modell:
    existiert das Ergebnis-JSON, werden die Zeilen daraus geschrieben, ohne LLM-Aufrufe."""
    src = db.load_source(ctx.conn, source_id)
    s = ctx.settings
    t0 = time.monotonic()
    with events.step(ctx.conn, source_id, STEP_CANDIDATES, "Kandidaten werden gesucht") as st:
        events.set_source_status(ctx.conn, source_id, "scoring", None)
        tv_id, tv_version, words = common.load_transcript(ctx, source_id)
        heat = _load_heat(ctx, src)
        brief = dict(src.get("brief") or {})
        brand = {"country": src.get("country"), "address": src.get("address"), "learned_weights": src.get("learned_weights")}
        weights = story_engine.resolve_weights(brand["learned_weights"])
        tenant = Tenant(id=src["workspace_id"], tier=src["tier"], allow_us_subprocessors=bool(src.get("allow_us_subprocessors")))

        llm_usage: list[dict] = []
        # ResidencyError bei nicht erlaubtem Provider; der Sink sammelt für job_costs und bucht Token auf usage_periods
        llm = LLM(tenant, cost_sink=usage.llm_sink(ctx.conn, src["workspace_id"], llm_usage), s=s)
        model = llm.model()
        if not model:
            raise RuntimeError(
                f"Kein Sprachmodell für Provider {llm.provider} konfiguriert "
                "(BEDROCK_MODEL_ID, MISTRAL_MODEL oder SELFHOST_LLM_MODEL setzen, für Entwicklung LLM_PROVIDER=local-heuristic)"
            )
        versions = story_engine.prompt_versions()
        key = candidates_key_for(tv_id, tv_version, brief, versions, llm.provider, model, weights)

        cached = ctx.store.exists("derived", key)
        if cached:
            report = story_engine.DetectReport.from_json(ctx.store.get_json("derived", key))
            log.info("candidates source=%s cached key=%s n=%s", source_id, key[:24], len(report.candidates))
        else:

            def _progress(done: int, total: int, n: int) -> None:
                common.heartbeat("chapter", done, total)
                st.progress(done / max(total, 1), f"Kapitel {done} von {total} bewertet, {n} Kandidaten")

            report = story_engine.run(words, brief, brand, heat, llm, weights=weights, on_progress=_progress)
            ctx.store.put_json("derived", key, report.to_json())

        ids = _write_rows(ctx, source_id, report.candidates)
        events.set_source_status(ctx.conn, source_id, "ready", None)
        costlog.record(
            ctx.conn,
            costlog.Cost(
                workspace_id=src["workspace_id"],
                source_id=source_id,
                job_type="llm_candidates",
                provider=llm.provider,
                model_id=model,
                source_minutes=float(src.get("duration_s") or 0.0) / 60.0,
                cpu_seconds=time.monotonic() - t0,
                llm_input_tokens=sum(int(u.get("in", 0)) for u in llm_usage),
                llm_output_tokens=sum(int(u.get("out", 0)) for u in llm_usage),
            ),
            s,
        )
        st.finish(
            f"{len(report.candidates)} Kandidaten aus {report.chapters} Kapiteln, {report.gate_passed} ohne Einwand",
            candidates=len(report.candidates),
            gate_passed=report.gate_passed,
            chapters=report.chapters,
            provider=llm.provider,
            model_id=model,
            prompt_versions=versions,
            discarded=report.discarded,
            proposals=report.proposals,
            transcript_version=tv_version,
            cached=cached,
            key=key,
        )
    return ids


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
    "candidates_key_for",
    "detect_candidates",
    "heatmap",
    "heatmap_key_for",
    "notify",
    "render_pack",
    "run_detect_candidates",
    "run_heatmap",
]
