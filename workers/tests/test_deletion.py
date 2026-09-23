"""Lösch-Activity ``delete_entity`` mit Fake-DB und lokalem Storage: Nachweis, Reihenfolge, Anonymisierung, Fehlerpfad."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chopstr_worker.activities import deletion

SEGMENTS = [{"start": 0.0, "end": 5.0, "role": "body"}]


@pytest.fixture
def project(fake_db, fake_context, monkeypatch):
    """Eine Quelle mit allem, was der Worker anlegt: Keys, Clips, Versionen, Events, Freigabe."""
    store = fake_context.store
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, audio_key="audio/a.wav", proxy_key="proxy/p.mp4", status="ready")
    fake_db.sources[sid]["temporal_workflow_id"] = f"project-{sid}"
    store.put_bytes("sources", "uploads/in.mp4", b"video")
    store.put_bytes("derived", "audio/a.wav", b"audio")  # proxy fehlt absichtlich (zählt als bereits weg)
    fake_db.add_transcript_version(sid, [{"text": "Hallo", "start": 0.0, "end": 0.5}])
    fake_db.add_transcript_correction(sid)
    cid = fake_db.add_candidate(sid, SEGMENTS)
    clip = fake_db.add_clip(sid, cid, "tiktok", SEGMENTS, status="rendered")
    keys = {ext: f"renders/{clip}/abc.{ext}" for ext in ("mp4", "srt", "vtt", "jpg", "ass")}
    fake_db.clips[clip].update(file_key=keys["mp4"], srt_key=keys["srt"], vtt_key=keys["vtt"], poster_key=keys["jpg"])
    for k in keys.values():
        store.put_bytes("derived", k, b"x")
    store.put_bytes("derived", f"renders/{clip}/old.mp4", b"x")  # verwaister Render, nur über list() zu finden
    fake_db.add_hook_version(clip)
    fake_db.caption_versions.append({"id": "cv1", "clip_id": clip, "version": 1, "ass_key": keys["ass"], "srt_key": keys["srt"]})
    fake_db.add_guest_approval(clip)
    for step, key in (("transcribe_de", "asr/h1.json"), ("diarize", "diar/h2.json"), ("heatmap", "heatmap/h3.json"), ("detect_candidates", "candidates/h4.json")):
        fake_db.events.append({"source_id": sid, "step": step, "status": "finished", "progress": 1.0, "message": None, "payload": {"key": key}})
        store.put_bytes("derived", key, b"{}")
    fake_db.events.append({"source_id": sid, "step": "render", "status": "finished", "progress": 1.0, "message": None, "payload": {"clip_id": clip}})
    terminated: list[str] = []
    monkeypatch.setattr(deletion, "terminate_workflow", lambda wf_id, s=None, reason="": terminated.append(wf_id) or True)
    return {"wid": wid, "pid": pid, "sid": sid, "cid": cid, "clip": clip, "keys": keys, "terminated": terminated}


def _all_keys(store, bucket: str) -> list[str]:
    return store.list(bucket, "")


def _add_clip(fake_db, store, sid, cand, delete_after, platform: str = "linkedin", status: str = "rendered"):
    """Zweiter Clip an derselben Quelle, komplett mit Dateien, Captions, Hook und Freigabe."""
    clip = fake_db.add_clip(sid, cand, platform, SEGMENTS, status=status, delete_after=delete_after)
    keys = {ext: f"renders/{clip}/neu.{ext}" for ext in ("mp4", "srt", "vtt", "jpg", "ass")}
    fake_db.clips[clip].update(file_key=keys["mp4"], srt_key=keys["srt"], vtt_key=keys["vtt"], poster_key=keys["jpg"])
    for k in keys.values():
        store.put_bytes("derived", k, b"x")
    fake_db.add_hook_version(clip)
    fake_db.caption_versions.append({"id": f"cv-{clip}", "clip_id": clip, "version": 1, "ass_key": keys["ass"], "srt_key": keys["srt"]})
    fake_db.add_guest_approval(clip)
    return clip, keys


def test_source_deletion_with_proof_and_anonymized_row(fake_db, fake_context, project):
    sid, clip = project["sid"], project["clip"]
    job = fake_db.add_deletion_job(project["wid"], "source", sid, reason="user_request", requested_by="user-1")
    out = deletion.run_delete_entity(fake_context, job)

    assert out["status"] == "done" and out["job_id"] == job
    row = fake_db.deletion_jobs[job]
    assert row["status"] == "done" and row["finished_at"] is not None and row["error"] is None
    assert project["terminated"] == [f"project-{sid}"]

    proof = row["keys_deleted"]
    by_key = {(p["bucket"], p["key"]): p for p in proof}
    assert by_key[("sources", "uploads/in.mp4")]["existed"] is True
    assert by_key[("derived", "proxy/p.mp4")]["existed"] is False  # bereits weg, trotzdem im Nachweis
    for k in list(project["keys"].values()) + [f"renders/{clip}/old.mp4", "asr/h1.json", "diar/h2.json", "heatmap/h3.json", "candidates/h4.json"]:
        assert ("derived", k) in by_key and by_key[("derived", k)]["deleted_at"]
    assert _all_keys(fake_context.store, "sources") == [] and _all_keys(fake_context.store, "derived") == []

    assert row["rows_deleted"] == {
        "caption_versions": 1, "hook_versions": 1, "guest_approvals": 1, "clips": 1, "candidates": 1,
        "transcript_corrections": 1, "transcript_versions": 1, "pipeline_events": 5, "clips_retained": 0,
    }  # fmt: skip
    assert fake_db.clips == {} and fake_db.hook_versions == [] and fake_db.caption_versions == [] and fake_db.guest_approvals == []
    assert fake_db.candidates == [] and fake_db.transcript_versions == [] and fake_db.transcript_corrections == [] and fake_db.events == []

    src = fake_db.sources[sid]
    assert src["title"] == "gelöscht" and src["original_filename"] is None and src["storage_key"] == ""
    assert src["audio_key"] is None and src["proxy_key"] is None and src["sha256"] is None and src["brief"] == {}
    assert src["status"] == "deleted" and src["deleted_at"] is not None and src["temporal_workflow_id"] is None

    audit = [a for a in fake_db.audit_log if a["action"] == "source.deleted"]
    assert len(audit) == 1 and audit[0]["actor_type"] == "system" and audit[0]["entity_id"] == sid
    assert audit[0]["payload"]["job_id"] == job and audit[0]["payload"]["requested_by"] == "user-1"
    assert audit[0]["payload"]["keys"] == len(proof) and audit[0]["payload"]["rows"]["clips"] == 1

    # idempotent: erledigte Jobs werden nicht wiederholt
    again = deletion.run_delete_entity(fake_context, job)
    assert again["skipped"] is True and len(fake_db.audit_log) == 1


def test_terminate_failure_is_only_logged(fake_db, fake_context, project, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("Temporal nicht erreichbar")

    monkeypatch.setattr(deletion, "terminate_workflow", _boom)
    job = fake_db.add_deletion_job(project["wid"], "source", project["sid"])
    assert deletion.run_delete_entity(fake_context, job)["status"] == "done"
    assert fake_db.sources[project["sid"]]["status"] == "deleted"


def test_missing_source_marks_job_failed_and_raises(fake_db, fake_context):
    wid = fake_db.add_workspace()
    job = fake_db.add_deletion_job(wid, "source", "00000000-0000-0000-0000-000000000000")
    with pytest.raises(LookupError):
        deletion.run_delete_entity(fake_context, job)
    row = fake_db.deletion_jobs[job]
    assert row["status"] == "failed" and "nicht gefunden" in row["error"] and row["finished_at"] is not None
    assert [a["action"] for a in fake_db.audit_log] == ["source.delete_failed"]


def test_clip_deletion_removes_files_and_marks_clip_deleted(fake_db, fake_context, project):
    clip = project["clip"]
    job = fake_db.add_deletion_job(project["wid"], "clip", clip)
    out = deletion.run_delete_entity(fake_context, job)
    assert out["status"] == "done"
    row = fake_db.deletion_jobs[job]
    assert row["status"] == "done" and row["error"] is None
    assert {p["key"] for p in row["keys_deleted"]} == {*project["keys"].values(), f"renders/{clip}/old.mp4"}
    assert row["rows_deleted"] == {"caption_versions": 1, "hook_versions": 1, "guest_approvals": 1}
    assert fake_context.store.list("derived", f"renders/{clip}/") == []
    c = fake_db.clips[clip]
    assert c["file_key"] is None and c["poster_key"] is None and c["status"] == "deleted"  # Migration 0004
    assert fake_context.store.exists("sources", "uploads/in.mp4")  # Quelle unberührt
    assert [a["action"] for a in fake_db.audit_log] == ["clip.deleted"]


# -- Zwei Fristen: Rohmaterial 30 Tage, Renderings 90 Tage (Migration 0006) ----------------------
def test_retention_source_deletion_keeps_clip_with_running_deadline(fake_db, fake_context, project):
    """Der Aufräumlauf nimmt das Rohmaterial, lässt aber den Clip stehen, dessen eigene Frist noch läuft."""
    sid = project["sid"]
    live, live_keys = _add_clip(fake_db, fake_context.store, sid, project["cid"], datetime.now(UTC) + timedelta(days=60))
    job = fake_db.add_deletion_job(project["wid"], "source", sid, reason="retention")

    assert deletion.run_delete_entity(fake_context, job)["status"] == "done"
    row = fake_db.deletion_jobs[job]
    assert row["rows_deleted"] == {
        "caption_versions": 1, "hook_versions": 1, "guest_approvals": 1, "clips": 1, "candidates": 1,
        "transcript_corrections": 1, "transcript_versions": 1, "pipeline_events": 5, "clips_retained": 1,
    }  # fmt: skip

    # Der überlebende Clip: Zeile da, Status unverändert, Dateien da, abhängige Zeilen da
    assert list(fake_db.clips) == [live] and fake_db.clips[live]["status"] == "rendered"
    for k in live_keys.values():
        assert fake_context.store.exists("derived", k)
    assert [r["clip_id"] for r in fake_db.caption_versions] == [live]
    assert [r["clip_id"] for r in fake_db.hook_versions] == [live]
    assert [r["clip_id"] for r in fake_db.guest_approvals] == [live]
    assert not ({p["key"] for p in row["keys_deleted"]} & set(live_keys.values()))

    # Rohmaterial und der Clip ohne eigene Frist sind weg, die Quellenzeile ist anonymisiert
    assert not fake_context.store.exists("sources", "uploads/in.mp4")
    for k in ("audio/a.wav", "asr/h1.json", "diar/h2.json", "heatmap/h3.json", "candidates/h4.json", *project["keys"].values()):
        assert not fake_context.store.exists("derived", k)
    assert fake_db.candidates == [] and fake_db.transcript_versions == [] and fake_db.events == []
    src = fake_db.sources[sid]
    assert src["status"] == "deleted" and src["title"] == "gelöscht" and src["storage_key"] == ""
    assert fake_db.audit_log[-1]["payload"]["rows"]["clips_retained"] == 1  # ehrlicher Nachweis


def test_retention_source_deletion_takes_clip_whose_deadline_passed(fake_db, fake_context, project):
    """Ist die Clipfrist ebenfalls abgelaufen, geht der Clip mit der Quelle."""
    sid = project["sid"]
    gone, gone_keys = _add_clip(fake_db, fake_context.store, sid, project["cid"], datetime.now(UTC) - timedelta(minutes=1))
    job = fake_db.add_deletion_job(project["wid"], "source", sid, reason="retention")

    assert deletion.run_delete_entity(fake_context, job)["status"] == "done"
    row = fake_db.deletion_jobs[job]
    assert row["rows_deleted"]["clips"] == 2 and row["rows_deleted"]["clips_retained"] == 0
    assert row["rows_deleted"]["caption_versions"] == 2 and row["rows_deleted"]["guest_approvals"] == 2
    assert fake_db.clips == {} and gone not in fake_db.clips
    assert set(gone_keys.values()) <= {p["key"] for p in row["keys_deleted"]}
    assert _all_keys(fake_context.store, "derived") == [] and _all_keys(fake_context.store, "sources") == []
    assert fake_db.caption_versions == [] and fake_db.hook_versions == [] and fake_db.guest_approvals == []


@pytest.mark.parametrize("reason", ["user_request", "gdpr_request", "workspace_deleted"])
def test_deletion_request_takes_every_clip(reason, fake_db, fake_context, project):
    """Ein Löschverlangen und die Workspace-Löschung lassen keinen Clip übrig — auch nicht mit laufender Frist."""
    sid = project["sid"]
    live, live_keys = _add_clip(fake_db, fake_context.store, sid, project["cid"], datetime.now(UTC) + timedelta(days=60))
    job = fake_db.add_deletion_job(project["wid"], "source", sid, reason=reason)

    assert deletion.run_delete_entity(fake_context, job)["status"] == "done"
    row = fake_db.deletion_jobs[job]
    assert row["rows_deleted"]["clips"] == 2 and row["rows_deleted"]["clips_retained"] == 0
    assert fake_db.clips == {} and live not in fake_db.clips
    assert set(live_keys.values()) <= {p["key"] for p in row["keys_deleted"]}
    assert _all_keys(fake_context.store, "derived") == [] and _all_keys(fake_context.store, "sources") == []
    assert fake_db.caption_versions == [] and fake_db.hook_versions == [] and fake_db.guest_approvals == []


def test_workspace_deletion_sweeps_clips_of_already_anonymized_source(fake_db, fake_context, project):
    """Nach einem Aufräumlauf ist die Quelle ``deleted``; die Workspace-Löschung muss ihren Clip trotzdem finden."""
    sid, wid = project["sid"], project["wid"]
    live, live_keys = _add_clip(fake_db, fake_context.store, sid, project["cid"], datetime.now(UTC) + timedelta(days=60))
    retention_job = fake_db.add_deletion_job(wid, "source", sid, reason="retention")
    deletion.run_delete_entity(fake_context, retention_job)
    assert list(fake_db.clips) == [live] and fake_db.sources[sid]["status"] == "deleted"

    job = fake_db.add_deletion_job(wid, "workspace", wid, reason="user_request")
    assert deletion.run_delete_entity(fake_context, job)["status"] == "done"
    assert fake_db.clips == {}
    for k in live_keys.values():
        assert not fake_context.store.exists("derived", k)
    assert _all_keys(fake_context.store, "derived") == []


def test_brand_profile_deletion_removes_assets(fake_db, fake_context, project):
    wid, pid = project["wid"], project["pid"]
    other = fake_db.add_brand_profile(wid)
    fake_db.add_brand_asset(wid, pid, "font", f"brand/{pid}/font/aa.otf")
    fake_db.add_brand_asset(wid, pid, "logo", f"brand/{pid}/logo/bb.png")
    fake_db.add_brand_asset(wid, other, "logo", f"brand/{other}/logo/cc.png")
    for a in fake_db.brand_assets.values():
        fake_context.store.put_bytes("derived", a["storage_key"], b"x")
    job = fake_db.add_deletion_job(wid, "brand_profile", pid)
    assert deletion.run_delete_entity(fake_context, job)["status"] == "done"
    row = fake_db.deletion_jobs[job]
    assert row["rows_deleted"] == {"brand_assets": 2} and len(row["keys_deleted"]) == 2
    assert not fake_context.store.exists("derived", f"brand/{pid}/font/aa.otf")
    assert fake_context.store.exists("derived", f"brand/{other}/logo/cc.png")
    assert [a["brand_profile_id"] for a in fake_db.brand_assets.values()] == [other]
    assert [a["action"] for a in fake_db.audit_log] == ["brand_profile.deleted"]


def test_workspace_deletion_creates_source_jobs_then_assets(fake_db, fake_context, project):
    wid, pid = project["wid"], project["pid"]
    sid2 = fake_db.add_source(wid, "uploads/second.mp4", status="ready")
    fake_context.store.put_bytes("sources", "uploads/second.mp4", b"v")
    gone = fake_db.add_source(wid, "", status="deleted")  # schon gelöscht: kein neuer Job
    fake_db.add_brand_asset(wid, pid, "font", f"brand/{pid}/font/aa.otf")
    fake_context.store.put_bytes("derived", f"brand/{pid}/font/aa.otf", b"x")
    job = fake_db.add_deletion_job(wid, "workspace", wid, reason="user_request", requested_by="owner-1")

    out = deletion.run_delete_entity(fake_context, job)
    assert out["status"] == "done"
    sub = [j for j in fake_db.deletion_jobs.values() if j["id"] != job]
    assert {j["entity_id"] for j in sub} == {project["sid"], sid2} and gone not in {j["entity_id"] for j in sub}
    assert all(j["entity"] == "source" and j["reason"] == "workspace_deleted" and j["status"] == "done" for j in sub)
    assert all(j["requested_by"] == "owner-1" and j["workspace_id"] == wid for j in sub)
    assert fake_db.sources[sid2]["status"] == "deleted" and fake_db.sources[project["sid"]]["status"] == "deleted"
    row = fake_db.deletion_jobs[job]
    assert row["rows_deleted"] == {"brand_assets": 1, "source_jobs": 2, "source_jobs_failed": 0}
    assert fake_db.brand_assets == {} and fake_context.store.list("derived", "") == []
    actions = [a["action"] for a in fake_db.audit_log]
    assert actions.count("source.deleted") == 2 and actions[-1] == "workspace.deleted"


def test_workspace_deletion_reports_failed_source_jobs(fake_db, fake_context, project, monkeypatch):
    wid = project["wid"]
    fake_context.store.delete("sources", "uploads/in.mp4")
    original = deletion.HANDLERS["source"]

    def _flaky(ctx, job):
        if job["entity_id"] == project["sid"]:
            raise RuntimeError("S3 nicht erreichbar")
        return original(ctx, job)

    monkeypatch.setitem(deletion.HANDLERS, "source", _flaky)
    job = fake_db.add_deletion_job(wid, "workspace", wid)
    out = deletion.run_delete_entity(fake_context, job)
    assert out["status"] == "failed" and "1 von 1 Quellen" in out["error"]
    assert fake_db.deletion_jobs[job]["status"] == "failed"
    assert [a["action"] for a in fake_db.audit_log] == ["source.delete_failed", "workspace.delete_failed"]


def test_find_expired_and_enqueue(fake_db, fake_context):
    now = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    wid = fake_db.add_workspace()
    old = fake_db.add_source(wid, "uploads/old.mp4", status="ready", delete_after=now - timedelta(days=1))
    fake_db.add_source(wid, "uploads/fresh.mp4", status="ready", delete_after=now + timedelta(days=5))
    fake_db.add_source(wid, "", status="deleted", delete_after=now - timedelta(days=9))
    busy = fake_db.add_source(wid, "uploads/busy.mp4", status="ready", delete_after=now - timedelta(days=2))
    fake_db.add_deletion_job(wid, "source", busy, status="running")
    fake_db.add_source(wid, "uploads/none.mp4", status="ready")  # ohne Frist
    ws_due = fake_db.add_workspace(deletion_requested_at=now - timedelta(days=31), deletion_scheduled_for=now - timedelta(days=1))
    fake_db.add_workspace(deletion_requested_at=now - timedelta(days=1), deletion_scheduled_for=now + timedelta(days=29))
    fake_db.add_workspace(deletion_scheduled_for=now - timedelta(days=1))  # ohne Anforderung: nie

    found = deletion.run_find_expired(fake_context, now)
    assert found == {"sources": [old], "clips": [], "workspaces": [ws_due]}

    job = deletion.enqueue(fake_context, "source", old, "retention")
    row = fake_db.deletion_jobs[job]
    assert row["workspace_id"] == wid and row["entity"] == "source" and row["reason"] == "retention" and row["status"] == "queued"
    assert deletion.run_find_expired(fake_context, now)["sources"] == []  # jetzt offener Job

    wjob = deletion.enqueue(fake_context, "workspace", ws_due, "retention")
    assert fake_db.deletion_jobs[wjob]["workspace_id"] == ws_due
    with pytest.raises(ValueError):
        deletion.enqueue(fake_context, "source", old, "weil")
    with pytest.raises(LookupError):
        deletion.enqueue(fake_context, "source", "fehlt", "retention")


def test_find_expired_clips_and_enqueue_clip(fake_db, fake_context):
    now = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/in.mp4", status="ready")
    cand = fake_db.add_candidate(sid, SEGMENTS)
    due = fake_db.add_clip(sid, cand, "tiktok", SEGMENTS, status="rendered", delete_after=now - timedelta(days=1))
    fake_db.add_clip(sid, cand, "linkedin", SEGMENTS, status="rendered", delete_after=now + timedelta(days=30))
    fake_db.add_clip(sid, cand, "reels", SEGMENTS, status="deleted", delete_after=now - timedelta(days=9))
    busy = fake_db.add_clip(sid, cand, "shorts", SEGMENTS, status="rendered", delete_after=now - timedelta(days=2))
    fake_db.add_deletion_job(wid, "clip", busy, status="running")
    fake_db.add_clip(sid, cand, "x", SEGMENTS, status="rendered")  # ohne Frist

    assert deletion.run_find_expired(fake_context, now)["clips"] == [due]

    job = deletion.enqueue(fake_context, "clip", due, "retention")
    row = fake_db.deletion_jobs[job]
    assert row["workspace_id"] == wid and row["entity"] == "clip" and row["reason"] == "retention" and row["status"] == "queued"
    assert deletion.run_find_expired(fake_context, now)["clips"] == []  # jetzt offener Job
    with pytest.raises(LookupError):
        deletion.enqueue(fake_context, "clip", "fehlt", "retention")


def test_storage_list_prefix(local_store):
    local_store.put_bytes("derived", "renders/c1/a.mp4", b"1")
    local_store.put_bytes("derived", "renders/c1/sub/b.srt", b"2")
    local_store.put_bytes("derived", "renders/c2/c.mp4", b"3")
    assert local_store.list("derived", "renders/c1/") == ["renders/c1/a.mp4", "renders/c1/sub/b.srt"]
    assert local_store.list("derived", "renders/c9/") == []
    assert local_store.list("derived", "renders/c2/c.mp4") == ["renders/c2/c.mp4"]
