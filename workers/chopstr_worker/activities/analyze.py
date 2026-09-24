"""Activities ``heatmap``, ``detect_candidates`` (Phase 2: Story-Engine), ``notify``; ``render_pack`` (Phase 3)
kommt aus ``activities.render`` und wird hier nur re-exportiert.

``heatmap`` läuft parallel zur Transkription und nutzt deshalb primär das Audio-Signal. Liegt das
ASR-Ergebnis bereits im Storage (Re-Run), fließt auch der Text-Anteil ein (``signals.combined``).
``detect_candidates`` lädt Transkript, Briefing, Markenprofil und Heatmap, lässt ``pipeline.story_engine``
laufen und schreibt ``candidates`` nach ``packages/schema/CANDIDATES.md``.

Seit dem Wegfall des Auswahlschritts legt ``detect_candidates`` im selben Zug für **jeden** Kandidaten
eine ``clips``-Zeile an (``auto_create_clips``) und setzt den Kandidaten auf ``human_verdict = 'accepted'``.
Damit ist die Warteschlange des Renderers (``clips.status = 'draft'`` mit angenommenem Kandidaten)
ohne menschliches Zutun gefüllt. Weil beide Wege — der lokale Worker und die Temporal-Activity —
durch ``run_detect_candidates`` laufen, hängt die Clip-Erzeugung an genau einer Stelle.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from .. import costlog, db, decision_log, editorial, events, outbox, storage, usage
from ..pipeline import copy_engine, signals, story_engine
from ..providers_llm import LLM
from ..residency import Tenant
from . import common
from .render import STEP_RENDER, ad_label_for, render_pack
from .transcribe import asr_key_for

log = logging.getLogger("chopstr.activities.analyze")

STEP_HEATMAP = "heatmap"
STEP_CANDIDATES = "detect_candidates"
# v2: Die Nutzlast traegt zusaetzlich den reinen Audioanteil (audio_values). Ohne Versionswechsel
# bliebe eine vorhandene Heatmap liegen und die Bewertung bekaeme nie ein Klangsignal zu sehen.
SIGNALS_VERSION = "signals_v2"

# -- Automatische Clips (ohne Auswahlschritt) ---------------------------------------------------
# Gründerentscheidung: alle Kandidaten bekommen einen Clip, immer Hochformat, je Kandidat genau einer.
AUTO_CLIP_ASPECT = "9:16"
AUTO_CLIP_PLATFORM = "reels"  # Rückfall, wenn an der Quelle kein Markenprofil hängt
AUTO_VERDICT_REASON = "automatisch angenommen (ohne Auswahlschritt)"
# Rundung der Kandidatenfenster für den Dublettenschutz (Zehntelsekunden)
_WINDOW_DIGITS = 1

SQL_DEFAULT_PLATFORM = (
    "select p.default_platform from sources s left join brand_profiles p on p.id = s.brand_profile_id where s.id = %s"
)
SQL_CLIP_FOR_CANDIDATE = "select id from clips where candidate_id = %s limit 1"
SQL_CLIP_WINDOWS = (
    "select k.start_s, k.end_s from clips c join candidates k on k.id = c.candidate_id where c.source_id = %s"
)
# Re-Run: die noch nicht gerenderten Automatik-Clips und ihre Kandidaten weichen dem neuen Ergebnis.
# Menschliche Urteile haben immer ein ``verdict_by`` und bleiben deshalb unberührt.
SQL_DROP_AUTO_CLIPS = (
    "delete from clips where status = 'draft' and candidate_id in "
    "(select id from candidates where source_id = %s and verdict_by is null and verdict_reason = %s)"
)
SQL_DROP_AUTO_CANDIDATES = (
    "delete from candidates where source_id = %s and verdict_by is null and verdict_reason = %s "
    "and not exists (select 1 from clips c where c.candidate_id = candidates.id)"
)
# Die Kandidaten, die einen Lauf ueberleben, weil jemand sie beurteilt hat.
SQL_SURVIVING_CANDIDATES = "select start_s, end_s from candidates where source_id = %s"


def wellenform_key_for(audio_key: str) -> str:
    """Key der Wellenform. Haengt nur an der Audiospur, nicht an Transkript oder Prompts: die
    Lautstaerke aendert sich nicht, wenn ein Modell wechselt."""
    return storage.derived_key(audio_key, {"bin_s": signals.WELLENFORM_BIN_S}, SIGNALS_VERSION, "json", prefix="wellenform")


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
        wkey = wellenform_key_for(audio_key)
        # Die Wellenform gehoert zur Zeitleiste und nicht zur Bewertung, haengt aber an derselben
        # Audiodatei. Sie hier mitzunehmen spart einen zweiten Download; fehlt sie, wird sie auch
        # dann erzeugt, wenn die Heatmap schon vorliegt.
        if ctx.store.exists("derived", key) and ctx.store.exists("derived", wkey):
            _merke_wellenform(ctx, source_id, wkey)
            st.finish("Heatmap bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
            return key
        local = common.ensure_local_audio(ctx, source_id, audio_key)
        if not ctx.store.exists("derived", wkey):
            try:
                ctx.store.put_json("derived", wkey, signals.wellenform(str(local)))
            except Exception as exc:  # eine fehlende Wellenform kostet Bedienkomfort, keinen Clip
                log.warning("wellenform failed source=%s error=%s", source_id, exc.__class__.__name__)
        _merke_wellenform(ctx, source_id, wkey)
        if ctx.store.exists("derived", key):
            st.finish("Heatmap bereits vorhanden, Schritt übersprungen", skipped=True, key=key)
            return key
        audio = signals.audio_heatmap(str(local))
        heat = signals.combined(str(local), words, audio=audio)
        payload = signals.to_payload(heat, audio=audio)
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
    """Idempotenz-Key: Transkriptversion, Briefing, Prompt-Versionen, Provider/Modell, Gewichte,
    Engine UND redaktionelle Grundlage.

    Die Grundlage gehoert dazu, weil sie das Ergebnis bestimmt: Laengengrenzen, Kontextzugabe,
    Gewichte der Rubrik. Ohne sie bliebe nach einer Aenderung an der Richtlinie das alte Ergebnis
    aus dem Zwischenspeicher stehen, und die Aenderung sieht aus, als haette sie nicht gewirkt."""
    try:
        policy = editorial.policy_version()
    except Exception:  # ohne Richtlinie lieber weiterarbeiten als gar nicht
        policy = "unbekannt"
    params = {
        "transcript_version": tv_version,
        "brief": brief,
        "prompt_versions": prompt_versions,
        "provider": provider,
        "model": model,
        "weights": weights,
        "engine": story_engine.ENGINE_VERSION,
        "policy": policy,
    }
    return storage.derived_key(f"transcript/{tv_id}", params, story_engine.CONTRACT, "json", prefix="candidates")


def _merke_wellenform(ctx: common.Context, source_id: str, key: str) -> None:
    """Den Key an der Quelle vermerken, damit die Oberflaeche ihn ohne Umweg findet."""
    if not ctx.store.exists("derived", key):
        return
    try:
        db.update(ctx.conn, "sources", {"id": source_id}, waveform_key=key)
    except Exception as exc:  # ohne die Spalte (Migration 0010) laeuft alles andere weiter
        log.warning("waveform_key not writable source=%s error=%s", source_id, exc.__class__.__name__)


def _drop_stale_auto_rows(ctx: common.Context, source_id: str) -> None:
    """Re-Run-Aufräumen für die Automatik: Ohne diesen Schritt überlebt jeder automatisch angenommene
    Kandidat den Lauf (``human_verdict`` ist gesetzt) und das neue Ergebnis käme obendrauf — doppelte
    Kandidaten und doppelte Clips. Entfernt werden deshalb die Automatik-Clips, die noch nicht gerendert
    sind (``draft``), und anschließend die Automatik-Kandidaten, an denen danach kein Clip mehr hängt.
    Gerenderte Ergebnisse und alles mit menschlichem Urteil (``verdict_by`` gesetzt) bleiben stehen."""
    ctx.conn.execute(SQL_DROP_AUTO_CLIPS, (source_id, AUTO_VERDICT_REASON))
    ctx.conn.execute(SQL_DROP_AUTO_CANDIDATES, (source_id, AUTO_VERDICT_REASON))


def _write_rows(ctx: common.Context, source_id: str, cands: list[story_engine.CandidateResult]) -> list[str]:
    """Alte Kandidaten ohne Urteil löschen (Re-Run), neue Zeilen schreiben; Zeilen mit Urteil bleiben.

    Ein Kandidat, der eine überlebende Zeile wiederholt, wird nicht geschrieben. Ohne das entstehen
    bei jedem erneuten Lauf Dubletten: gelöscht wird nur, was noch kein Urteil hat, die beurteilten
    Zeilen bleiben, und das neue Ergebnis enthält dieselben Stellen noch einmal. An einer echten
    Quelle gemessen standen danach 17 Kandidaten für 11 Clips, darunter fünf Paare mit exakt
    derselben Spanne. In der Prüfliste sieht ein Mensch denselben Moment dann zweimal.

    Verglichen wird mit demselben Maß wie in der Auswahl (Anteil am kürzeren Abschnitt), damit nicht
    zwei verschiedene Begriffe von „dasselbe" nebeneinander stehen."""
    _drop_stale_auto_rows(ctx, source_id)
    ctx.conn.execute("delete from candidates where source_id = %s and human_verdict is null", (source_id,))
    ueberlebende = [
        (float(r[0] or 0.0), float(r[1] or 0.0))
        for r in db.fetch_all(ctx.conn, SQL_SURVIVING_CANDIDATES, (source_id,))
    ]
    ids = []
    for c in cands:
        if any(
            story_engine.gemeinsamer_anteil(c.start_s, c.end_s, a, b) >= story_engine.OVERLAP_SUPPRESS_ANTEIL
            for a, b in ueberlebende
        ):
            log.info("kandidat uebersprungen source=%s span=%.1f-%.1fs grund=deckt_beurteilten_ab", source_id, c.start_s, c.end_s)
            ids.append("")
            continue
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


def _window(start: Any, end: Any) -> tuple[float, float]:
    """Kandidatenfenster als Schlüssel für den Dublettenschutz (Zehntelsekunden)."""
    return round(float(start or 0.0), _WINDOW_DIGITS), round(float(end or 0.0), _WINDOW_DIGITS)


def clip_platform(ctx: common.Context, source_id: str) -> str:
    """Standard-Plattform aus dem Markenprofil der Quelle; ohne Profil oder Wert ``reels``.

    Das Seitenverhältnis hängt bewusst nicht daran (immer ``9:16``), die Plattform steuert nur
    Untertitel-Voreinstellung und Branding im Render."""
    try:
        row = db.fetch_one(ctx.conn, SQL_DEFAULT_PLATFORM, (source_id,))
    except Exception as exc:  # Markenprofil ist Komfort, die Automatik darf daran nicht scheitern
        log.warning("default platform not readable source=%s error=%s", source_id, exc.__class__.__name__)
        return AUTO_CLIP_PLATFORM
    value = str(row[0]).strip() if row and row[0] else ""
    if value not in copy_engine.PLATFORMS:
        return AUTO_CLIP_PLATFORM
    return value


def auto_create_clips(
    ctx: common.Context, source_id: str, src: dict, candidate_ids: list[str], cands: list[story_engine.CandidateResult]
) -> list[str]:
    """Je Kandidat genau eine ``clips``-Zeile, damit der Renderer ohne Auswahlschritt weiterarbeitet.

    Felder wie in ``createClips`` der Web-App (``apps/web/lib/repo/postgres.ts``): ``composition`` aus
    den Segmenten des Kandidaten, ``title_card`` aus der Rubrik, ``ad_label`` nach Land, ``destination``
    gleich der Plattform, ``status = 'draft'``. Abweichend davon ist ``aspect`` fest ``9:16`` und
    ``created_by`` leer (kein Mensch beteiligt). ``delete_after`` setzt der Trigger aus Migration 0006.

    Idempotent auf zwei Ebenen: ein Kandidat mit vorhandenem Clip wird übersprungen, und ein Fenster,
    zu dem an dieser Quelle schon ein Clip existiert, bekommt keinen zweiten (zweiter Lauf, gelöschte
    oder bereits gerenderte Clips)."""
    platform = clip_platform(ctx, source_id)
    ad_label = ad_label_for(dict(src.get("brief") or {}), src.get("country") or "AT")
    taken = {_window(r[0], r[1]) for r in db.fetch_all(ctx.conn, SQL_CLIP_WINDOWS, (source_id,))}
    created: list[str] = []
    for candidate_id, cand in zip(candidate_ids, cands):
        if not candidate_id:
            continue
        if db.fetch_one(ctx.conn, SQL_CLIP_FOR_CANDIDATE, (candidate_id,)) is not None:
            continue
        row = cand.to_row()
        key = _window(row["start_s"], row["end_s"])
        if key in taken:
            continue
        title_card = str((row.get("rubric") or {}).get("suggested_title_card") or "").strip() or None
        inserted = db.insert(
            ctx.conn,
            "clips",
            returning="id",
            source_id=source_id,
            candidate_id=candidate_id,
            platform=platform,
            destination=platform,
            aspect=AUTO_CLIP_ASPECT,
            composition=db.jsonb(row["segments"]),
            title_card=title_card,
            ad_label=ad_label,
            status="draft",
            created_by=None,
        )
        db.update(
            ctx.conn,
            "candidates",
            {"id": candidate_id},
            human_verdict="accepted",
            verdict_reason=AUTO_VERDICT_REASON,
            verdict_at=datetime.now(UTC),
        )
        taken.add(key)
        created.append(str(inserted[0]) if inserted else "")
    log.info("auto clips source=%s platform=%s aspect=%s created=%s", source_id, platform, AUTO_CLIP_ASPECT, len(created))
    return created


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
        # Kein Auswahlschritt mehr: die Clips entstehen hier, nicht erst nach einem Urteil in der Oberfläche.
        clips = auto_create_clips(ctx, source_id, src, ids, report.candidates)
        decisions = decision_log.record_detect_report(
            ctx.conn, src["workspace_id"], source_id, src.get("brand_profile_id"), report, ids,
            str(brief.get("platform") or "linkedin"),
        )  # fmt: skip
        outbox.candidates_ready(ctx.conn, src["workspace_id"], source_id, len(report.candidates), report.gate_passed)
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
            f"{len(report.candidates)} Kandidaten aus {report.chapters} Kapiteln, {len(clips)} Clips angelegt",
            candidates=len(report.candidates),
            clips=len(clips),
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
            decisions=decisions,
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
    "AUTO_CLIP_ASPECT",
    "AUTO_CLIP_PLATFORM",
    "AUTO_VERDICT_REASON",
    "SIGNALS_VERSION",
    "STEP_CANDIDATES",
    "STEP_HEATMAP",
    "STEP_RENDER",
    "auto_create_clips",
    "candidates_key_for",
    "clip_platform",
    "detect_candidates",
    "heatmap",
    "heatmap_key_for",
    "notify",
    "render_pack",
    "run_detect_candidates",
    "run_heatmap",
]
