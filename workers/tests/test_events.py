from __future__ import annotations

import pytest

from chopstr_worker import events


def test_emit_and_status(fake_db):
    events.emit(fake_db, "s1", "probe_and_extract", "started", "los")
    events.emit(fake_db, "s1", "probe_and_extract", "progress", progress=1.7)
    assert fake_db.events[0]["status"] == "started"
    assert fake_db.events[1]["progress"] == 1.0  # geklemmt
    with pytest.raises(ValueError):
        events.emit(fake_db, "s1", "x", "unknown")
    with pytest.raises(ValueError):
        events.set_source_status(fake_db, "s1", "nope")


def test_step_success_writes_started_and_finished(fake_db):
    with events.step(fake_db, "s1", "transcribe_de", "Start") as st:
        st.progress(0.5, "halb")
        st.finish("fertig", word_count=12)
    assert fake_db.statuses("transcribe_de") == ["started", "progress", "finished"]
    fin = fake_db.events_for("transcribe_de")[-1]
    assert fin["message"] == "fertig"
    assert fin["payload"]["word_count"] == 12
    assert "duration_s" in fin["payload"]
    assert fin["progress"] == 1.0


def test_step_failure_writes_failed_and_sets_source_status(fake_db):
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "src/x.mp4")
    with pytest.raises(RuntimeError), events.step(fake_db, sid, "probe_and_extract"):
        raise RuntimeError("ffmpeg hat keinen Ton gefunden")
    assert fake_db.statuses("probe_and_extract") == ["started", "failed"]
    msg = fake_db.events_for("probe_and_extract")[-1]["message"]
    assert msg.startswith("Audio konnte nicht extrahiert werden: ")
    assert "ffmpeg hat keinen Ton gefunden" in msg
    assert fake_db.sources[sid]["status"] == "failed"
    assert fake_db.sources[sid]["status_message"] == msg


def test_failure_message_no_em_dash_and_truncated():
    msg = events.failure_message("diarize", RuntimeError("x" * 500))
    assert msg.startswith("Sprechererkennung fehlgeschlagen: ")
    assert len(msg) < 400
    assert "—" not in msg and "–" not in msg
    assert events.failure_message("weird", ValueError("")) == "Schritt weird fehlgeschlagen: ValueError"
