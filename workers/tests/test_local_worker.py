"""Lokaler Testmodus (``chopstr_worker/local_worker.py``) mit der Fake-DB: Reihenfolge, Fehlerpfad, keine Dublette."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chopstr_worker import local_worker


@pytest.fixture
def calls():
    return []


def _pipeline(calls, fail_at: str | None = None, final_status: str = "ready"):
    """Sechs gemockte ``run_*``-Funktionen; die letzte setzt den Quellstatus wie ``detect_candidates``."""

    def make(name):
        def run(ctx, source_id):
            calls.append((name, source_id))
            if name == fail_at:
                raise RuntimeError("Modell nicht geladen")
            src = ctx.conn.sources[source_id]
            if name == local_worker.SOURCE_PIPELINE[0][0]:
                src["status"] = "ingesting"
            if name == local_worker.SOURCE_PIPELINE[-1][0]:
                src["status"] = final_status
            return name

        return run

    return tuple((name, make(name)) for name, _fn in local_worker.SOURCE_PIPELINE)


@pytest.fixture
def worker(monkeypatch, calls, fake_context):
    monkeypatch.setattr(local_worker, "SOURCE_PIPELINE", _pipeline(calls))
    monkeypatch.setattr(local_worker, "run_render_pack", lambda ctx, cand, dest: calls.append(("render", cand, dest)) or "clip")
    monkeypatch.setattr(local_worker.deletion, "run_delete_entity", lambda ctx, job: calls.append(("delete", job)) or {"status": "done", "entity": "clip", "keys": 0})
    monkeypatch.setattr(local_worker.publish, "run_publish_clip", lambda ctx, pub: calls.append(("publish", pub)) or {"status": "published"})
    monkeypatch.setattr(local_worker.webhooks, "run_dispatch_outbox", lambda ctx, limit: calls.append(("dispatch", limit)) or {"events": 0, "deliveries": 0})
    monkeypatch.setattr(local_worker.webhooks, "run_find_due_deliveries", lambda ctx, now, limit: ["d1"])
    monkeypatch.setattr(local_worker.webhooks, "run_deliver_webhook", lambda ctx, did: calls.append(("deliver", did)) or {"status": "delivered", "attempt": 1})
    monkeypatch.setattr(local_worker, "app_reachable", lambda s=None, timeout=0: True)
    monkeypatch.setattr(local_worker.internal_api, "replan", lambda s=None, http=None: calls.append(("replan",)) or {"replanned": 0, "platforms": []})
    return local_worker.LocalWorker(interval_s=0.2, outbox_every_s=60.0)


def _seed(fake_db):
    ws = fake_db.add_workspace()
    old = fake_db.add_source(ws, "uploads/old.mp4", created_at=1)
    new = fake_db.add_source(ws, "uploads/new.mp4", created_at=2)
    ready = fake_db.add_source(ws, "uploads/ready.mp4", status="ready", created_at=0)
    segs = [{"start": 0.0, "end": 15.0, "role": "main"}]
    accepted = fake_db.add_candidate(ready, segs, human_verdict="accepted")
    pending = fake_db.add_candidate(ready, segs, human_verdict=None)
    clip_ok = fake_db.add_clip(ready, accepted, "tiktok", segs)
    clip_wait = fake_db.add_clip(ready, pending, "tiktok", segs)
    clip_done = fake_db.add_clip(ready, accepted, "linkedin", segs, status="rendered")
    job = fake_db.add_deletion_job(ws, "clip", clip_done)
    fake_db.add_deletion_job(ws, "clip", clip_done, status="done")
    now = datetime.now(UTC)
    due = fake_db.add_publication(ws, clip_done, scheduled_for=now - timedelta(minutes=5))
    fake_db.add_publication(ws, clip_done, scheduled_for=now + timedelta(hours=1))
    fake_db.add_publication(ws, clip_done, status="published", scheduled_for=now - timedelta(hours=1))
    return {"old": old, "new": new, "accepted": accepted, "clip_ok": clip_ok, "clip_wait": clip_wait, "job": job, "due": due}


def test_once_processes_queues_in_order(fake_db, worker, calls):
    ids = _seed(fake_db)
    counts = worker.run_once()
    assert counts == {"sources": 2, "clips": 1, "deletions": 1, "publications": 1, "metrics": 0, "webhooks": 1}

    steps = [name for name, _fn in local_worker.SOURCE_PIPELINE]
    source_calls = [c for c in calls if c[0] in steps]
    # älteste Quelle zuerst, alle sechs Schritte in Reihenfolge, dann die nächste
    assert source_calls == [(s, ids["old"]) for s in steps] + [(s, ids["new"]) for s in steps]
    assert fake_db.sources[ids["old"]]["status"] == "ready" and fake_db.sources[ids["new"]]["status"] == "ready"

    kinds = [c[0] for c in calls if c[0] not in steps]
    assert kinds == ["render", "delete", "publish", "dispatch", "deliver"]
    assert ("render", ids["accepted"], f"tiktok:{ids['clip_ok']}") in calls  # Ziel "plattform:clip_id"
    assert ("delete", ids["job"]) in calls
    assert ("publish", ids["due"]) in calls
    assert worker.processed[-1][0] == "publication" and all(r == "ok" for _k, _i, r in worker.processed)


def test_second_pass_does_nothing_and_outbox_waits(fake_db, worker, calls):
    _seed(fake_db)
    worker.run_once()
    before = len(calls)
    # Quellen stehen auf ready, Clips auf rendered (durch die Mocks nicht, deshalb Status hier setzen)
    for c in fake_db.clips.values():
        c["status"] = "rendered"
    for j in fake_db.deletion_jobs.values():
        j["status"] = "done"
    for p in fake_db.publications.values():
        p["status"] = "published"
    counts = worker.run_once()
    assert counts == {"sources": 0, "clips": 0, "deletions": 0, "publications": 0, "metrics": 0, "webhooks": 0}
    assert len(calls) == before  # kein zweiter Outbox-Lauf innerhalb von 60 s


def test_source_failure_sets_failed_and_is_not_retried(fake_db, worker, calls, monkeypatch):
    monkeypatch.setattr(local_worker, "SOURCE_PIPELINE", _pipeline(calls, fail_at="transcribe_de"))
    ws = fake_db.add_workspace()
    sid = fake_db.add_source(ws, "uploads/x.mp4")
    counts = worker.run_once()
    assert counts["sources"] == 1
    src = fake_db.sources[sid]
    assert src["status"] == "failed"
    assert src["status_message"] == "Transkription fehlgeschlagen: Modell nicht geladen"
    steps = [name for name, _fn in local_worker.SOURCE_PIPELINE]
    assert [c[0] for c in calls if c[0] in steps] == ["probe_and_extract", "transcribe_de"]  # danach kein Schritt mehr
    assert ("source", sid) in worker.failed
    assert fake_db.outbox_events[-1]["event"] == "source.failed"

    # Selbst wenn jemand den Status zurücksetzt: derselbe Prozess versucht es nicht noch einmal
    src["status"] = "uploaded"
    assert worker.run_once()["sources"] == 0
    assert len([c for c in calls if c[0] in steps]) == 2


def test_failed_status_is_not_duplicated(fake_db, worker, calls, monkeypatch):
    """Setzt der Schritt den Status selbst auf failed (wie events.step), schreibt der Worker keine zweite Meldung."""

    def failing(ctx, source_id):
        ctx.conn.sources[source_id]["status"] = "failed"
        ctx.conn.sources[source_id]["status_message"] = "Audio konnte nicht extrahiert werden: kaputt"
        raise RuntimeError("kaputt")

    monkeypatch.setattr(local_worker, "SOURCE_PIPELINE", (("probe_and_extract", failing),))
    ws = fake_db.add_workspace()
    sid = fake_db.add_source(ws, "uploads/x.mp4")
    worker.run_once()
    assert fake_db.sources[sid]["status_message"] == "Audio konnte nicht extrahiert werden: kaputt"
    assert not [e for e in fake_db.outbox_events if e["event"] == "source.failed"]


def test_render_failure_is_remembered(fake_db, worker, calls, monkeypatch):
    ids = _seed(fake_db)

    def boom(ctx, cand, dest):
        ctx.conn.clips[ids["clip_ok"]]["status"] = "failed"
        raise RuntimeError("ffmpeg fehlt")

    monkeypatch.setattr(local_worker, "run_render_pack", boom)
    assert worker.run_once()["clips"] == 1
    assert ("clip", ids["clip_ok"]) in worker.failed
    fake_db.clips[ids["clip_ok"]]["status"] = "draft"
    assert worker.run_once()["clips"] == 0


def test_publications_skipped_when_app_unreachable(fake_db, worker, calls, monkeypatch, caplog):
    ids = _seed(fake_db)
    monkeypatch.setattr(local_worker, "app_reachable", lambda s=None, timeout=0: False)
    with caplog.at_level("WARNING", logger="chopstr.local_worker"):
        counts = worker.run_once()
    assert counts["publications"] == 0
    assert ("publish", ids["due"]) not in calls
    assert local_worker.HINT_APP_UNREACHABLE in caplog.text
    assert fake_db.publications[ids["due"]]["status"] == "scheduled"  # bleibt fällig


def test_stop_request_pauses_after_current_step(fake_db, worker, calls, monkeypatch):
    def stopping(ctx, source_id):
        calls.append(("probe_and_extract", source_id))
        worker.request_stop()

    steps = (("probe_and_extract", stopping),) + local_worker.SOURCE_PIPELINE[1:]
    monkeypatch.setattr(local_worker, "SOURCE_PIPELINE", steps)
    ws = fake_db.add_workspace()
    sid = fake_db.add_source(ws, "uploads/x.mp4")
    worker.run_once()
    assert [c[0] for c in calls] == ["probe_and_extract"]
    assert worker.processed == [("source", sid, "paused:probe_and_extract")]


def test_app_reachable_probe(monkeypatch):
    from chopstr_worker import config

    monkeypatch.setenv("APP_INTERNAL_URL", "http://127.0.0.1:1")  # Port 1: nichts lauscht
    s = config.reload()
    assert local_worker.app_reachable(s, timeout=0.3) is False
    monkeypatch.setenv("APP_INTERNAL_URL", "")
    assert local_worker.app_reachable(config.reload()) is False


def test_cli_once_returns_zero_without_work(fake_db, worker, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://x@localhost/x")
    from chopstr_worker import config

    config.reload()
    assert local_worker.main(["--once", "--log-level", "WARNING"]) == 0


def test_run_forever_checks_assets_before_the_loop(worker, monkeypatch, tmp_path):
    """L7: Fehlt eine gemeinsame Datei, endet der lokale Worker mit der deutschen Meldung der Startprüfung
    statt mit einem Traceback aus der Statuszeile; die Schleife läuft gar nicht erst an."""
    from chopstr_worker import editorial

    passes = []
    monkeypatch.setattr(worker, "run_once", lambda: passes.append(1) or {})
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path / "gibt_es_nicht"))
    editorial.clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            worker.run_forever()
    finally:
        editorial.clear_cache()
    assert str(excinfo.value).startswith("Der Worker startet nicht, weil gemeinsame Dateien fehlen")
    assert passes == []


def test_once_runs_the_startup_check_too(monkeypatch, tmp_path):
    """``--once`` prüft die gemeinsamen Dateien wie ``run_forever`` und endet mit derselben Meldung."""
    from chopstr_worker import config, editorial

    passes = []
    monkeypatch.setenv("DATABASE_URL", "postgres://x@127.0.0.1:1/x")
    monkeypatch.setenv("EDITORIAL_DIR", str(tmp_path / "gibt_es_nicht"))
    monkeypatch.setattr(local_worker.LocalWorker, "run_once", lambda self: passes.append(1) or {})
    monkeypatch.setattr(local_worker.LocalWorker, "install_signal_handlers", lambda self: None)
    config.reload()
    editorial.clear_cache()
    try:
        with pytest.raises(SystemExit) as excinfo:
            local_worker.main(["--once"])
    finally:
        editorial.clear_cache()
        monkeypatch.undo()
        config.reload()
    assert str(excinfo.value).startswith("Der Worker startet nicht, weil gemeinsame Dateien fehlen")
    assert passes == []


# -- Messreihen (Migration 0019) -----------------------------------------------------------------
@pytest.fixture
def polling(monkeypatch, fake_context):
    from chopstr_worker import config

    monkeypatch.setenv("METRICS_POLLING", "1")
    fake_context.settings = config.reload()
    yield
    monkeypatch.delenv("METRICS_POLLING", raising=False)
    config.reload()


def _tracked(fake_db, **fields):
    ws = fake_db.add_workspace()
    sid = fake_db.add_source(ws, "uploads/x.mp4", status="ready")
    segs = [{"start": 0.0, "end": 15.0, "role": "main"}]
    cand = fake_db.add_candidate(sid, segs, human_verdict="accepted")
    clip = fake_db.add_clip(sid, cand, "shorts", segs, status="rendered")
    now = datetime.now(UTC)
    base = {"status": "manual", "tracking": "link", "next_snapshot_at": now - timedelta(minutes=1), "external_id": "dQw4w9WgXcQ"}
    base.update(fields)
    return fake_db.add_publication(ws, clip, "youtube", **base)


def test_metrics_polling_is_off_by_default(fake_db, worker, calls, monkeypatch):
    seen = []
    monkeypatch.setattr(local_worker.publish, "run_snapshot", lambda ctx, pid: seen.append(pid) or {"status": "ok"})
    _tracked(fake_db)
    assert worker.run_once()["metrics"] == 0
    assert seen == []


def test_metrics_polling_runs_due_snapshots_only(fake_db, worker, calls, monkeypatch, polling):
    seen = []
    monkeypatch.setattr(local_worker.publish, "run_snapshot", lambda ctx, pid: seen.append(pid) or {"status": "ok", "window": None})
    due = _tracked(fake_db)
    _tracked(fake_db, next_snapshot_at=datetime.now(UTC) + timedelta(hours=1))  # noch nicht fällig
    _tracked(fake_db, next_snapshot_at=None)  # fertig gemessen
    _tracked(fake_db, tracking="off")  # abgeschaltet
    counts = worker.run_once()
    assert counts["metrics"] == 1 and seen == [due]
    assert ("snapshot", due, "ok") in worker.processed


def test_metrics_polling_survives_missing_migration(fake_db, worker, calls, monkeypatch, polling, caplog):
    fake_db.missing_columns = {"next_snapshot_at"}
    _tracked(fake_db)
    with caplog.at_level("WARNING", logger="chopstr.local_worker"):
        counts = worker.run_once()
        worker.run_once()
    assert counts["metrics"] == 0 and counts["webhooks"] == 1  # der Rest des Durchlaufs läuft weiter
    assert caplog.text.count("Migration 0019") == 1  # nur einmal gemeldet


def test_metrics_polling_waits_for_the_web_app(fake_db, worker, calls, monkeypatch, polling):
    seen = []
    monkeypatch.setattr(local_worker.publish, "run_snapshot", lambda ctx, pid: seen.append(pid) or {"status": "ok"})
    monkeypatch.setattr(local_worker, "app_reachable", lambda s=None, timeout=0: False)
    _tracked(fake_db)
    assert worker.run_once()["metrics"] == 0 and seen == []


def test_metrics_polling_remembers_database_failures(fake_db, worker, calls, monkeypatch, polling):
    def boom(ctx, pid):
        raise RuntimeError("db weg")

    monkeypatch.setattr(local_worker.publish, "run_snapshot", boom)
    pid = _tracked(fake_db)
    assert worker.run_once()["metrics"] == 1
    assert ("snapshot", pid) in worker.failed
    assert worker.run_once()["metrics"] == 0


def test_metrics_polling_replans_hourly_and_measures_replanned_links(fake_db, worker, calls, monkeypatch, polling):
    seen = []
    monkeypatch.setattr(local_worker.publish, "run_snapshot", lambda ctx, pid: seen.append(pid) or {"status": "ok", "window": None})
    waiting = _tracked(fake_db, next_snapshot_at=None)

    def replan(s=None, http=None):
        calls.append(("replan",))
        fake_db.publications[waiting]["next_snapshot_at"] = datetime.now(UTC) - timedelta(seconds=1)
        return {"replanned": 1, "platforms": ["youtube"]}

    monkeypatch.setattr(local_worker.internal_api, "replan", replan)
    assert worker.run_once()["metrics"] == 1 and seen == [waiting]  # im selben Durchlauf gemessen
    worker.run_once()
    assert calls.count(("replan",)) == 1  # höchstens einmal je Stunde
    worker._last_replan -= local_worker.REPLAN_EVERY_S
    worker.run_once()
    assert calls.count(("replan",)) == 2


def test_metrics_polling_survives_failing_replan(fake_db, worker, calls, monkeypatch, polling, caplog):
    seen = []
    monkeypatch.setattr(local_worker.publish, "run_snapshot", lambda ctx, pid: seen.append(pid) or {"status": "ok", "window": None})

    def boom(s=None, http=None):
        raise RuntimeError("web weg")

    monkeypatch.setattr(local_worker.internal_api, "replan", boom)
    due = _tracked(fake_db)
    with caplog.at_level("WARNING", logger="chopstr.local_worker"):
        assert worker.run_once()["metrics"] == 1
    assert seen == [due] and "replan failed" in caplog.text
