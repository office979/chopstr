"""Lokaler Testmodus ohne Temporal: ``python -m chopstr_worker.local_worker [--once] [--interval 3]``.

Eine Polling-Schleife über die Datenbank, die dieselben Activity-Funktionen (``run_*``) wie der
Temporal-Worker aufruft, ohne Temporal, MinIO oder GPU:

  (a) ``sources`` mit ``status = 'uploaded'`` (älteste zuerst, eine nach der anderen):
      probe_and_extract -> transcribe_de -> diarize -> heatmap -> fuse_and_nlp -> detect_candidates
      ``detect_candidates`` legt am Ende selbst für jeden Kandidaten eine ``clips``-Zeile an und nimmt
      den Kandidaten an; einen manuellen Auswahlschritt gibt es nicht mehr.
  (b) ``clips`` mit ``status = 'draft'``, deren Kandidat ``human_verdict = 'accepted'`` hat: ``render_pack``
      (durch (a) ist das im nächsten Durchlauf ohne menschliches Zutun gefüllt)
  (c) ``deletion_jobs`` mit ``status = 'queued'``: ``delete_entity``
  (d) ``publications`` mit ``status = 'scheduled'`` und fälligem ``scheduled_for``: ``publish_clip``
      (nur wenn ``APP_INTERNAL_URL`` erreichbar ist, sonst Hinweis und überspringen)
  (e) alle ``OUTBOX_EVERY_S`` Sekunden ``dispatch_outbox`` plus fällige ``deliver_webhook``

Fehler setzen den jeweiligen Status auf ``failed`` (mit deutscher Meldung) und die ID landet zusätzlich in
einem Merker im Speicher, damit nichts endlos wiederholt wird. Logging nur mit IDs, Dauern und Zählern,
keine Transkriptinhalte. SIGINT und SIGTERM beenden die Schleife nach dem laufenden Schritt.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import signal
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from . import config, db, editorial, events
from .activities import analyze, common, deletion, ingest, nlp, publish, transcribe, webhooks
from .activities.render import run_render_pack
from .pipeline import captions_de, reframe, story_engine

log = logging.getLogger("chopstr.local_worker")

OUTBOX_EVERY_S = 60.0
BATCH_LIMIT = 20
APP_PROBE_TIMEOUT_S = 1.5
HINT_APP_UNREACHABLE = "Web-App unter APP_INTERNAL_URL nicht erreichbar, Veröffentlichung wird übersprungen"

# Reihenfolge der Quell-Pipeline, gleiche Funktionen wie im ClipProjectWorkflow (dort teils parallel)
SOURCE_PIPELINE: tuple[tuple[str, Callable[[common.Context, str], Any]], ...] = (
    (ingest.STEP, ingest.run),
    (transcribe.STEP_ASR, transcribe.run_transcribe),
    (transcribe.STEP_DIAR, transcribe.run_diarize),
    (analyze.STEP_HEATMAP, analyze.run_heatmap),
    (nlp.STEP, nlp.run),
    (analyze.STEP_CANDIDATES, analyze.run_detect_candidates),
)

SQL_PENDING_SOURCES = "select id from sources where status = 'uploaded' order by created_at asc limit %s"
SQL_SOURCE_STATUS = "select status, status_message from sources where id = %s"
SQL_PENDING_CLIPS = (
    "select c.id, c.candidate_id, c.platform from clips c join candidates k on k.id = c.candidate_id "
    "where c.status = 'draft' and k.human_verdict = 'accepted' order by c.created_at asc limit %s"
)
SQL_PENDING_DELETIONS = "select id from deletion_jobs where status = 'queued' order by requested_at asc limit %s"
SQL_DUE_PUBLICATIONS = (
    "select id from publications where status = 'scheduled' and scheduled_for is not null and scheduled_for <= %s "
    "order by scheduled_for asc limit %s"
)


def _now() -> datetime:
    return datetime.now(UTC)


def app_reachable(s: config.Settings | None = None, timeout: float = APP_PROBE_TIMEOUT_S) -> bool:
    """TCP-Verbindung zu Host und Port aus ``APP_INTERNAL_URL``; kein HTTP-Aufruf, kein Secret."""
    s = s or config.settings()
    parts = urlsplit((s.app_internal_url or "").strip())
    host = parts.hostname
    if not host:
        return False
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class LocalWorker:
    """Ein Durchlauf (``run_once``) oder eine Schleife (``run_forever``) über alle Warteschlangen."""

    def __init__(self, interval_s: float = 3.0, outbox_every_s: float = OUTBOX_EVERY_S, limit: int = BATCH_LIMIT):
        self.interval_s = max(0.2, float(interval_s))
        self.outbox_every_s = max(0.0, float(outbox_every_s))
        self.limit = max(1, int(limit))
        self.stop_requested = False
        # Merker gegen Endlosschleifen: (Art, ID) von allem, was in diesem Prozess schon fehlgeschlagen ist
        self.failed: set[tuple[str, str]] = set()
        self.processed: list[tuple[str, str, str]] = []  # (Art, ID, Ergebnis) für Tests und Logs
        self._last_outbox: float | None = None
        self._app_hint_logged = False

    # -- Steuerung ------------------------------------------------------------------------------
    def request_stop(self, *_args: Any) -> None:
        if not self.stop_requested:
            log.info("stop requested, finishing current step")
        self.stop_requested = True

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError):  # nicht im Hauptthread
                signal.signal(sig, self.request_stop)

    def run_forever(self) -> None:
        log.info("local worker start interval=%.1fs outbox_every=%.0fs", self.interval_s, self.outbox_every_s)
        # Welcher Stand ist geladen? Python liest Module beim Start, ein laufender Worker arbeitet
        # also mit dem Code von damals. Ohne diese Zeile sieht ein Lauf mit veraltetem Code genauso
        # aus wie ein richtiger, und man sucht den Fehler stundenlang in den Daten.
        log.info(
            "geladener Stand: engine=%s policy=%s prompts=%s signals=%s reframe=%s schriften=%s",
            story_engine.ENGINE_VERSION,
            editorial.policy_version(),
            ",".join(story_engine.prompt_versions()),
            analyze.SIGNALS_VERSION,
            reframe.REFRAME_VERSION,
            captions_de.schriften().get("version", "?"),
        )
        while not self.stop_requested:
            try:
                counts = self.run_once()
            except Exception as exc:  # z. B. Datenbank kurz weg: warten und erneut versuchen
                log.error("pass failed error=%s: %s", exc.__class__.__name__, str(exc)[:200])
                counts = {}
            if self.stop_requested:
                break
            if not any(counts.values()):
                self._sleep(self.interval_s)
        log.info("local worker stop")

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self.stop_requested and time.monotonic() < end:
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    # -- Ein Durchlauf ---------------------------------------------------------------------------
    def run_once(self) -> dict[str, int]:
        """Alle Warteschlangen einmal abarbeiten. Ergebnis: Zähler je Warteschlange."""
        counts = {"sources": 0, "clips": 0, "deletions": 0, "publications": 0, "webhooks": 0}
        ctx = common.open_context()
        try:
            counts["sources"] = self.process_sources(ctx)
            if not self.stop_requested:
                counts["clips"] = self.process_clips(ctx)
            if not self.stop_requested:
                counts["deletions"] = self.process_deletions(ctx)
            if not self.stop_requested:
                counts["publications"] = self.process_publications(ctx)
            if not self.stop_requested and self._outbox_due():
                counts["webhooks"] = self.process_outbox(ctx)
        finally:
            ctx.close()
        if any(counts.values()):
            log.info("pass done %s", " ".join(f"{k}={v}" for k, v in counts.items()))
        return counts

    def _outbox_due(self) -> bool:
        now = time.monotonic()
        if self._last_outbox is not None and now - self._last_outbox < self.outbox_every_s:
            return False
        self._last_outbox = now
        return True

    def _skip(self, kind: str, entity_id: str) -> bool:
        return (kind, entity_id) in self.failed

    def _note(self, kind: str, entity_id: str, result: str) -> None:
        self.processed.append((kind, entity_id, result))
        if result != "ok":
            self.failed.add((kind, entity_id))

    # -- (a) Quellen -----------------------------------------------------------------------------
    def process_sources(self, ctx: common.Context) -> int:
        done = 0
        for (sid,) in db.fetch_all(ctx.conn, SQL_PENDING_SOURCES, (self.limit,)):
            if self.stop_requested:
                break
            sid = str(sid)
            if self._skip("source", sid):
                continue
            self.process_source(ctx, sid)
            done += 1
        return done

    def process_source(self, ctx: common.Context, source_id: str) -> bool:
        """Die sechs Schritte nacheinander; beim ersten Fehler ``failed`` mit Meldung und Abbruch."""
        t0 = time.monotonic()
        log.info("source start id=%s", source_id)
        for step_name, fn in SOURCE_PIPELINE:
            ts = time.monotonic()
            try:
                fn(ctx, source_id)
            except Exception as exc:
                msg = events.failure_message(step_name, exc)
                log.error(
                    "source failed id=%s step=%s error=%s duration=%.1fs",
                    source_id, step_name, exc.__class__.__name__, time.monotonic() - ts,
                )  # fmt: skip
                self._mark_source_failed(ctx, source_id, msg)
                self._note("source", source_id, f"failed:{step_name}")
                return False
            log.info("source step id=%s step=%s duration=%.1fs", source_id, step_name, time.monotonic() - ts)
            if self.stop_requested and step_name != SOURCE_PIPELINE[-1][0]:
                log.warning("source paused id=%s after=%s (stop requested)", source_id, step_name)
                self._note("source", source_id, f"paused:{step_name}")
                return False
        log.info("source done id=%s duration=%.1fs", source_id, time.monotonic() - t0)
        self._note("source", source_id, "ok")
        return True

    @staticmethod
    def _mark_source_failed(ctx: common.Context, source_id: str, message: str) -> None:
        """``events.step`` hat den Status meist schon gesetzt (nicht bei heatmap); sonst hier, ohne Dublette."""
        try:
            row = db.fetch_one(ctx.conn, SQL_SOURCE_STATUS, (source_id,))
            if row is not None and row[0] == "failed":
                return
            events.set_source_status(ctx.conn, source_id, "failed", message)
        except Exception as exc:  # Status ist Komfort, der Merker verhindert die Wiederholung
            log.warning("source status update failed id=%s error=%s", source_id, exc.__class__.__name__)

    # -- (b) Clips -------------------------------------------------------------------------------
    def process_clips(self, ctx: common.Context) -> int:
        done = 0
        for clip_id, candidate_id, platform in db.fetch_all(ctx.conn, SQL_PENDING_CLIPS, (self.limit,)):
            if self.stop_requested:
                break
            clip_id, candidate_id = str(clip_id), str(candidate_id)
            if self._skip("clip", clip_id):
                continue
            t0 = time.monotonic()
            log.info("render start clip=%s candidate=%s platform=%s", clip_id, candidate_id, platform)
            try:
                run_render_pack(ctx, candidate_id, f"{platform}:{clip_id}")
            except Exception as exc:  # run_render_pack hat clips.status = failed und render_error gesetzt
                log.error("render failed clip=%s error=%s duration=%.1fs", clip_id, exc.__class__.__name__, time.monotonic() - t0)
                self._note("clip", clip_id, "failed")
            else:
                log.info("render done clip=%s duration=%.1fs", clip_id, time.monotonic() - t0)
                self._note("clip", clip_id, "ok")
            done += 1
        return done

    # -- (c) Löschaufträge -----------------------------------------------------------------------
    def process_deletions(self, ctx: common.Context) -> int:
        done = 0
        for (job_id,) in db.fetch_all(ctx.conn, SQL_PENDING_DELETIONS, (self.limit,)):
            if self.stop_requested:
                break
            job_id = str(job_id)
            if self._skip("deletion", job_id):
                continue
            t0 = time.monotonic()
            try:
                result = deletion.run_delete_entity(ctx, job_id)
            except Exception as exc:  # Job steht auf failed mit error
                log.error("deletion failed job=%s error=%s", job_id, exc.__class__.__name__)
                self._note("deletion", job_id, "failed")
            else:
                log.info("deletion done job=%s entity=%s status=%s keys=%s duration=%.1fs", job_id, result.get("entity"), result.get("status"), result.get("keys", 0), time.monotonic() - t0)
                self._note("deletion", job_id, "ok" if result.get("status") == "done" else "failed")
            done += 1
        return done

    # -- (d) Veröffentlichungen ------------------------------------------------------------------
    def process_publications(self, ctx: common.Context) -> int:
        rows = db.fetch_all(ctx.conn, SQL_DUE_PUBLICATIONS, (_now(), self.limit))
        pending = [str(r[0]) for r in rows if not self._skip("publication", str(r[0]))]
        if not pending:
            return 0
        if not app_reachable(ctx.settings):
            if not self._app_hint_logged:
                log.warning("%s (%s fällig)", HINT_APP_UNREACHABLE, len(pending))
                self._app_hint_logged = True
            return 0
        self._app_hint_logged = False
        done = 0
        for pub_id in pending:
            if self.stop_requested:
                break
            t0 = time.monotonic()
            try:
                result = publish.run_publish_clip(ctx, pub_id)
            except Exception as exc:  # Zeile steht auf failed mit Grund
                log.error("publish failed publication=%s error=%s", pub_id, exc.__class__.__name__)
                self._note("publication", pub_id, "failed")
            else:
                log.info("publish done publication=%s status=%s duration=%.1fs", pub_id, result.get("status"), time.monotonic() - t0)
                self._note("publication", pub_id, "ok" if result.get("status") == "published" else "failed")
            done += 1
        return done

    # -- (e) Outbox und Webhooks -----------------------------------------------------------------
    def process_outbox(self, ctx: common.Context) -> int:
        try:
            webhooks.run_dispatch_outbox(ctx, self.limit)
            due = webhooks.run_find_due_deliveries(ctx, _now(), self.limit)
        except Exception as exc:
            log.error("outbox dispatch failed error=%s", exc.__class__.__name__)
            return 0
        done = 0
        for delivery_id in due:
            if self.stop_requested:
                break
            try:
                result = webhooks.run_deliver_webhook(ctx, str(delivery_id))
            except Exception as exc:
                log.error("webhook failed delivery=%s error=%s", delivery_id, exc.__class__.__name__)
                continue
            log.info("webhook delivery=%s status=%s attempt=%s", delivery_id, result.get("status"), result.get("attempt"))
            done += 1
        return done


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="chopstr Worker im lokalen Testmodus (ohne Temporal)")
    ap.add_argument("--once", action="store_true", help="einen Durchlauf verarbeiten und beenden")
    ap.add_argument("--interval", type=float, default=3.0, help="Sekunden zwischen leeren Durchläufen (Default 3)")
    ap.add_argument("--outbox-every", type=float, default=OUTBOX_EVERY_S, help="Sekunden zwischen Outbox-Läufen (Default 60)")
    ap.add_argument("--limit", type=int, default=BATCH_LIMIT, help="Zeilen je Warteschlange und Durchlauf")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = config.settings()
    if not s.database_url:
        log.error("DATABASE_URL ist nicht gesetzt (scripts/local_env.sh laden)")
        return 2
    log.info(
        "local worker db=%s storage=%s llm=%s asr=%s device=%s",
        urlsplit(s.database_url).hostname, "local" if s.is_local_storage else "s3", s.llm_provider,
        s.asr_model_de or "(ASR_MODEL_DE fehlt)", s.asr_device,
    )  # fmt: skip
    worker = LocalWorker(interval_s=args.interval, outbox_every_s=args.outbox_every, limit=args.limit)
    worker.install_signal_handlers()
    if args.once:
        counts = worker.run_once()
        failed = sum(1 for _k, _i, r in worker.processed if r != "ok")
        log.info("once done %s failed=%s", " ".join(f"{k}={v}" for k, v in counts.items()), failed)
        return 1 if failed else 0
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
