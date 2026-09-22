"""Activities Ende-zu-Ende mit Fake-DB und lokalem Storage (ohne Temporal, ohne Modelle)."""

from __future__ import annotations

import pytest

from chopstr_worker import config
from chopstr_worker.activities import analyze, common
from chopstr_worker.activities import ingest as act_ingest
from chopstr_worker.activities import nlp as act_nlp
from chopstr_worker.activities import transcribe as act_asr
from chopstr_worker.activities.transcribe import asr_key_for, diar_key_for
from chopstr_worker.pipeline import transcribe as asr
from tests.conftest import make_test_video, requires_ffmpeg


@pytest.fixture
def source(fake_db, fake_context, tmp_path):
    video = make_test_video(tmp_path / "in.mp4", seconds=3.0)
    fake_context.store.put_file("sources", "uploads/in.mp4", video)
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid, brand_vocab=["chopstr"])
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid, expected_speakers=2)
    return sid


@requires_ffmpeg
def test_probe_and_extract_is_idempotent(fake_db, fake_context, source):
    out = act_ingest.run(fake_context, source)
    row = fake_db.sources[source]
    assert row["status"] == "transcribing"
    assert row["audio_key"] == out["audio_key"] and row["proxy_key"] == out["proxy_key"]
    assert row["sha256"] and row["duration_s"] > 2 and row["width"] == 640
    assert fake_context.store.exists("derived", out["audio_key"])
    assert fake_context.store.exists("derived", out["proxy_key"])
    assert fake_db.statuses("probe_and_extract")[0] == "started"
    assert fake_db.statuses("probe_and_extract")[-1] == "finished"
    assert fake_db.job_costs[-1]["job_type"] == "ingest"
    # Zweiter Lauf: Ableitungen werden übersprungen
    out2 = act_ingest.run(fake_context, source)
    assert out2["audio_key"] == out["audio_key"]
    fin = fake_db.events_for("probe_and_extract")[-1]["payload"]
    assert fin["audio_skipped"] is True and fin["proxy_skipped"] is True


@requires_ffmpeg
def test_transcribe_without_model_fails_with_event(fake_db, fake_context, source):
    act_ingest.run(fake_context, source)
    with pytest.raises(asr.TranscribeError):
        act_asr.run_transcribe(fake_context, source)
    ev = fake_db.events_for("transcribe_de")[-1]
    assert ev["status"] == "failed"
    assert ev["message"].startswith("Transkription fehlgeschlagen: ")
    assert "ASR_MODEL_DE" in ev["message"]


@requires_ffmpeg
def test_transcribe_skips_when_output_exists(fake_db, fake_context, source, monkeypatch):
    act_ingest.run(fake_context, source)
    monkeypatch.setenv("ASR_MODEL_DE", "dummy/model")
    config.reload()
    fake_context.settings = config.settings()
    src = fake_db.sources[source]
    key = asr_key_for(src["audio_key"], "de", ["chopstr"], "dummy/model", fake_context.settings)
    fake_context.store.put_json("derived", key, {"words": [], "model_id": "dummy/model", "variant": "de"})
    assert act_asr.run_transcribe(fake_context, source) == key
    assert fake_db.events_for("transcribe_de")[-1]["payload"]["skipped"] is True


@requires_ffmpeg
def test_heatmap_fuse_and_nlp_end_to_end(fake_db, fake_context, source, monkeypatch):
    act_ingest.run(fake_context, source)
    monkeypatch.setenv("ASR_MODEL_DE", "dummy/model")
    config.reload()
    fake_context.settings = config.settings()
    src = fake_db.sources[source]
    audio_key = src["audio_key"]

    words = [
        {"text": "Wir", "start": 0.0, "end": 0.2, "prob": 0.9},
        {"text": "haben", "start": 0.25, "end": 0.45, "prob": 0.9},
        {"text": "äh", "start": 0.5, "end": 0.6, "prob": 0.4},
        {"text": "2.4", "start": 0.7, "end": 0.9, "prob": 0.9},
        {"text": "Prozent", "start": 0.95, "end": 1.2, "prob": 0.9},
        {"text": "nicht", "start": 1.25, "end": 1.4, "prob": 0.9},
        {"text": "geschafft.", "start": 1.45, "end": 1.9, "prob": 0.9},
        {"text": "Genau.", "start": 2.0, "end": 2.3, "prob": 0.8},
    ]
    akey = asr_key_for(audio_key, "de", ["chopstr"], "dummy/model", fake_context.settings)
    fake_context.store.put_json("derived", akey, {"words": words, "model_id": "dummy/model", "variant": "de", "beta": False})
    dkey = diar_key_for(audio_key, 2, fake_context.settings.diarizer_model or asr._DEFAULT_DIARIZER)
    fake_context.store.put_json("derived", dkey, {"turns": [[0.0, 1.95, "SPEAKER_00"], [1.95, 3.0, "SPEAKER_01"]], "model_id": "diar-x"})

    hkey = analyze.run_heatmap(fake_context, source)
    heat = fake_context.store.get_json("derived", hkey)
    assert heat["text_included"] is True and heat["n_bins"] >= 2
    assert fake_db.events_for("heatmap")[-1]["status"] == "finished"

    tv_id = act_nlp.run(fake_context, source)
    assert tv_id
    tv = fake_db.transcript_versions[-1]
    assert tv["version"] == 1 and tv["origin"] == "asr"
    assert tv["asr_model_id"] == "dummy/model" and tv["diarizer_id"] == "diar-x"
    w = tv["words"]
    assert w[3]["text"] == "2,4"  # Zahlen erst nach dem Alignment normalisiert
    assert w[0]["speaker"] == "SPEAKER_00" and w[7]["speaker"] == "SPEAKER_01"
    assert w[2]["filler"] == "hard" and w[5]["negation"] is True
    assert w[6]["sentence_idx"] == 0 and w[7]["sentence_idx"] == 1
    assert tv["stats"]["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    assert tv["stats"]["sentence_count"] == 2
    assert fake_db.sources[source]["status"] == "ready"
    assert fake_db.job_costs[-1]["job_type"] == "nlp"

    # zweite Version zählt hoch
    act_nlp.run(fake_context, source)
    assert fake_db.transcript_versions[-1]["version"] == 2

    assert analyze.run_detect_candidates(fake_context, source) == []
    ev = fake_db.events_for("detect_candidates")[-1]
    assert ev["status"] == "skipped" and ev["message"] == "Kandidaten kommen in Phase 2"


def test_fuse_without_asr_output_fails_clearly(fake_db, fake_context):
    wid = fake_db.add_workspace()
    sid = fake_db.add_source(wid, "uploads/x.mp4", audio_key="audio/none.wav")
    with pytest.raises(RuntimeError, match="Transkript nicht im Speicher"):
        act_nlp.run(fake_context, sid)
    assert fake_db.events_for("fuse_and_nlp")[-1]["status"] == "failed"
    assert fake_db.sources[sid]["status"] == "failed"


def test_require_message():
    with pytest.raises(RuntimeError, match="Audio-Spur fehlt"):
        common.require({"audio_key": None}, "audio_key", "Audio-Spur")
