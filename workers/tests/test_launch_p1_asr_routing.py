"""Lane P1: Datenvertrag Transkript (Regel 13), Routing nach erkannter Sprache, Hotwords.

Ohne faster-whisper-Modell: ein Fake-Modell liefert Spracherkennung und Wörter. Der Lauf mit dem echten
Modell steht in ``test_launch_p1_asr_network.py`` (Marker ``network``).
"""

from __future__ import annotations

import wave
from types import SimpleNamespace

import numpy as np
import pytest

from chopstr_worker import config, editorial, storage
from chopstr_worker.activities import common
from chopstr_worker.activities import nlp as act_nlp
from chopstr_worker.activities import transcribe as act_asr
from chopstr_worker.pipeline import transcribe as asr


def _wav(path, seconds: float = 3.0, sr: int = 16000):
    x = (0.1 * np.sin(2 * np.pi * 200 * np.arange(int(seconds * sr)) / sr) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(x.tobytes())
    return path


class FakeModel:
    """Wie ``faster_whisper.WhisperModel``: ``transcribe`` und ``detect_language``; merkt sich die Aufrufe."""

    def __init__(self, text: str = "Wir zahlen heuer im Jänner mehr chopsta", langs=(("de", 0.97), ("en", 0.02))):
        self.text = text.split()
        self.langs = list(langs)
        self.calls: list[dict] = []
        self.detect_calls = 0

    def say(self, text: str) -> None:
        self.text = text.split()

    def detect_language(self, audio):
        self.detect_calls += 1
        return self.langs[0][0], self.langs[0][1], self.langs

    def transcribe(self, audio, **kw):
        self.calls.append(kw)
        words = [SimpleNamespace(word=f" {t}", start=0.3 * k, end=0.3 * k + 0.25, probability=0.9) for k, t in enumerate(self.text)]
        return [SimpleNamespace(words=words)], SimpleNamespace(language="de")


def _tokens(text: str) -> list[dict]:
    return [{"text": t} for t in text.split()]


@pytest.fixture
def model(monkeypatch):
    m = FakeModel()
    monkeypatch.setattr(asr, "load_model", lambda model_id, s=None: m)
    return m


def _settings(monkeypatch, **env):
    for k in ("ASR_AUTO_ROUTE", "ASR_MODEL_CH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ASR_MODEL_DE", "cstr/whisper-large-v3-turbo-german-int8_float32")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config.reload()


# -- Datenvertrag und Standardverhalten -----------------------------------------------------------


def test_default_route_is_profile_and_verbatim_without_detection(tmp_path, monkeypatch, model):
    s = _settings(monkeypatch)
    r = asr.transcribe(str(_wav(tmp_path / "a.wav")), "de", brand_vocab=["chopstr"], s=s)
    assert model.detect_calls == 0  # ohne ASR_AUTO_ROUTE keine Erkennung
    assert r.route["routing_reason"] == "profile" and r.route["verbatim"] is True
    assert r.route["time_source"] == asr.TIME_SOURCE_ASR and r.route["detected_variant"] is None
    assert r.to_dict()["route"]["model_id"] == s.asr_model_de
    # Befund Testmaterial (Notiz 010): das Wörterbuch geht nicht mehr in den Decoder, nur in die Nachkorrektur
    assert all(c["hotwords"] is None for c in model.calls)
    assert [w["text"] for w in r.words][-1] == "chopstr"  # „chopsta" über die Nachkorrektur
    assert r.route["hotwords"] == {"terms": 1, "decode": False}


def test_auto_route_detects_austrian_and_adds_austriacisms(tmp_path, monkeypatch, model):
    model.say("Heuer im Jänner hab ich eh ein Sackerl Paradeiser und eine Semmel gekauft passt")
    s = _settings(monkeypatch, ASR_AUTO_ROUTE="1")
    r = asr.transcribe(str(_wav(tmp_path / "a.wav")), "de", brand_vocab=["chopstr"], s=s, protected_terms=["PLACEMedia"])
    assert model.detect_calls == 1 and r.route["detected_variant"] == "de-AT"
    assert r.route["routing_reason"] == "detected_at" and r.route["austriacisms"] is True
    assert r.variant == "de" and r.model_id == s.asr_model_de
    assert r.route["hotwords"]["terms"] == 40  # Wörterbuch, geschützter Begriff, dann Austriazismen bis max_terms
    assert all(c["hotwords"] is None for c in model.calls)  # decode bleibt aus


def test_hotwords_reach_the_decoder_only_with_decode(tmp_path, monkeypatch, model):
    model.say("Heuer im Jänner ein Sackerl Paradeiser eine Semmel gekauft")
    s = _settings(monkeypatch, ASR_AUTO_ROUTE="1")
    monkeypatch.setattr(asr, "asr_settings", lambda policy=None: {**asr.ASR_DEFAULTS, "decode": True, "max_terms": 5})
    asr.transcribe(str(_wav(tmp_path / "a.wav")), "de", brand_vocab=["chopstr"], s=s, protected_terms=["PLACEMedia"])
    used = model.calls[-1]["hotwords"]
    assert used == "chopstr PLACEMedia Jänner Feber heuer"


def test_ch_detected_without_model_falls_back_with_hint(tmp_path, monkeypatch, model):
    model.say("Das isch nöd so schlimm gsi und mer händ chli öppis gmacht")
    s = _settings(monkeypatch, ASR_AUTO_ROUTE="1")
    r = asr.transcribe(str(_wav(tmp_path / "a.wav")), "de", s=s)
    assert r.route["detected_variant"] == "de-CH"
    assert r.route["routing_reason"] == asr.HINT_CH_NO_MODEL and asr.HINT_CH_NO_MODEL in r.route["hints"]
    assert r.variant == "de" and r.beta is False and r.route["verbatim"] is True
    assert r.stats["route_hints"] == [asr.HINT_CH_NO_MODEL]


def test_ch_detected_with_model_takes_the_beta_route(tmp_path, monkeypatch, model):
    model.say("Das isch nöd so schlimm gsi und mer händ chli öppis gmacht")
    s = _settings(monkeypatch, ASR_AUTO_ROUTE="1", ASR_MODEL_CH="models/swissgerman-ct2")
    r = asr.transcribe(str(_wav(tmp_path / "a.wav")), "de", s=s)
    assert r.variant == "de-CH" and r.model_id == "models/swissgerman-ct2"
    assert r.beta is True and r.route["verbatim"] is False and r.route["routing_reason"] == "detected_ch"


def test_sure_german_overrides_a_ch_profile_and_unsure_keeps_it(tmp_path, monkeypatch, model):
    model.say("Wir haben im letzten Jahr den Umsatz deutlich gesteigert und neue Kunden gewonnen")
    s = _settings(monkeypatch, ASR_AUTO_ROUTE="1", ASR_MODEL_CH="models/swissgerman-ct2")
    r = asr.transcribe(str(_wav(tmp_path / "a.wav")), "de-CH", s=s)
    assert r.variant == "de" and r.route["routing_reason"] == "detected_de"
    model.langs = [("de", 0.4), ("nl", 0.35)]
    r = asr.transcribe(str(_wav(tmp_path / "b.wav")), "de-CH", s=s)
    assert r.variant == "de-CH" and r.route["routing_reason"] == "unsure_profile_kept"


def test_non_german_is_a_hint_not_an_abort(tmp_path, monkeypatch, model):
    model.langs = [("en", 0.93), ("de", 0.05)]
    s = _settings(monkeypatch, ASR_AUTO_ROUTE="1")
    r = asr.transcribe(str(_wav(tmp_path / "a.wav")), "de", s=s)
    assert r.route["detected_variant"] == "unklar" and r.route["detected_language"] == "en"
    assert asr.HINT_NON_GERMAN in r.route["hints"] and r.words  # transkribiert trotzdem


# -- reine Funktionen ----------------------------------------------------------------------------------


def test_classify_variant_thresholds():
    de_words = _tokens("Wir zahlen heuer im Jänner ein Sackerl")
    assert asr.classify_variant({"de": 0.95}, de_words, 0.6)["detected_variant"] == "de-AT"
    assert asr.classify_variant({"de": 0.95}, de_words, 0.99)["detected_variant"] == "unklar"  # Lexikon zu unsicher
    plain = _tokens("Wir zahlen im Januar mehr")
    assert asr.classify_variant({"de": 0.95}, plain, 0.6)["detected_variant"] == "de"
    assert asr.classify_variant({"de": 0.5, "en": 0.1}, plain, 0.6)["detected_variant"] == "unklar"
    assert asr.classify_variant({}, [], 0.6)["detected_language"] == "unknown"


def test_sample_spans_head_and_middle():
    assert asr.sample_spans(0) == []
    assert asr.sample_spans(45.0) == [(0.0, 45.0)]
    assert asr.sample_spans(600.0) == [(0.0, 60.0), (285.0, 315.0)]


def test_build_hotwords_dedup_order_and_limits():
    assert asr.build_hotwords([], None) is None
    out = asr.build_hotwords(["chopstr", "PLACEMedia", "Chopstr"], ["placemedia", "Ö1"], ("Jänner", "Feber"), max_terms=4)
    assert out == "chopstr PLACEMedia Ö1 Jänner"
    assert asr.build_hotwords(["a" * 10, "b" * 10], max_chars=15) == "a" * 10
    assert len(asr.build_hotwords([], None, asr.AUSTRIACISMS, max_terms=200)) <= asr.HOTWORDS_MAX_CHARS


def test_austriacisms_list_is_large_and_clean():
    assert len(asr.AUSTRIACISMS) >= 60 and len(set(asr.AUSTRIACISMS)) == len(asr.AUSTRIACISMS)
    assert all(t.strip() == t and " " not in t for t in asr.AUSTRIACISMS)


def test_policy_values_v2_and_defaults_v1():
    v2 = editorial.load(2)
    assert asr.asr_settings(v2) == {"routing_enabled": True, "min_confidence": 0.6, "max_terms": 40, "decode": False, "ch_beta": True}
    assert asr.speaker_settings(v2) == {"overlap_min_ratio": 0.3, "energy_window_s": 0.1, "overlap_db": 10.0, "silence_dbfs": -45.0}
    assert asr.asr_settings(editorial.load(1)) == asr.ASR_DEFAULTS
    assert asr.speaker_settings(editorial.load(1)) == asr.SPEAKER_DEFAULTS


def test_invalid_policy_values_fail_loudly():
    import copy

    v2 = editorial.load(2)
    raw = copy.deepcopy(v2.roh)
    raw["asr"]["routing"]["min_confidence"] = 1.5
    bad = editorial.Policy(version=2, stand="", roh=raw)
    with pytest.raises(editorial.PolicyError, match="min_confidence"):
        asr.asr_settings(bad)
    raw = copy.deepcopy(v2.roh)
    del raw["speakers"]["multitrack"]["overlap_db"]
    with pytest.raises(editorial.PolicyError, match="speakers"):
        asr.speaker_settings(editorial.Policy(version=2, stand="", roh=raw))


# -- Activities: Keys, Event, stats.asr_route ---------------------------------------------------------


def _source(fake_db, fake_context, tmp_path, vocab=None):
    ws = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(ws, brand_vocab=vocab or [], protected_terms=["PLACEMedia"])
    fake_context.store.put_file("derived", "audio/t.wav", _wav(tmp_path / "t.wav", 2.0))
    return fake_db.add_source(ws, "uploads/x.mp4", audio_key="audio/t.wav", duration_s=2.0, brand_profile_id=pid)


def test_activity_key_unchanged_without_vocab_and_switch(fake_db, fake_context, tmp_path, monkeypatch, model):
    fake_context.settings = _settings(monkeypatch)
    sid = _source(fake_db, fake_context, tmp_path)
    key = act_asr.run_transcribe(fake_context, sid)
    assert key == act_asr.asr_key_for("audio/t.wav", "de", [], fake_context.settings.asr_model_de, fake_context.settings)
    ev = fake_db.events_for("transcribe_de")[-1]
    assert ev["payload"]["routing_reason"] == "profile" and ev["payload"]["verbatim"] is True


def test_activity_with_vocab_gets_a_new_key_and_fusion_finds_it(fake_db, fake_context, tmp_path, monkeypatch, model):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    fake_context.settings = _settings(monkeypatch)
    sid = _source(fake_db, fake_context, tmp_path, vocab=["chopstr"])
    key = act_asr.run_transcribe(fake_context, sid)
    s = fake_context.settings
    params = {"variant": "de", "vocab": common.vocab_hash(["chopstr"]), "window_s": s.asr_window_s, "overlap_s": s.asr_overlap_s}
    old = storage.derived_key("audio/t.wav", params, f"{act_asr.ASR_PIPELINE_VERSION}:{s.asr_model_de}", "json", prefix="asr")
    assert key != old  # Key vor Lane P1: Transkripte mit Decoder-Hotwords werden nicht wiederverwendet
    assert key == act_asr.asr_key_for("audio/t.wav", "de", ["chopstr"], s.asr_model_de, s)
    act_asr.run_diarize(fake_context, sid)
    act_nlp.run(fake_context, sid)
    tv = fake_db.transcript_versions[-1]
    assert tv["stats"]["asr_route"]["routing_reason"] == "profile"
    assert tv["stats"]["asr_route"]["verbatim"] is True and tv["stats"]["asr_route"]["time_source"] == asr.TIME_SOURCE_ASR
    assert "overlap_ratio" not in tv["stats"]  # ohne Überlappungsangabe keine Zahl
    assert tv["diarizer_id"] == asr.DIARIZER_NONE and tv["stats"]["diarization"] == "skipped"


def test_activity_auto_route_key_is_reconstructed_by_fusion(fake_db, fake_context, tmp_path, monkeypatch, model):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    model.say("Heuer im Jänner ein Sackerl Paradeiser eine Semmel gekauft passt")
    fake_context.settings = _settings(monkeypatch, ASR_AUTO_ROUTE="1")
    sid = _source(fake_db, fake_context, tmp_path, vocab=["chopstr"])
    act_asr.run_transcribe(fake_context, sid)
    ev = fake_db.events_for("transcribe_de")[-1]
    assert ev["payload"]["detected_variant"] == "de-AT" and ev["payload"]["routing_reason"] == "detected_at"
    act_asr.run_diarize(fake_context, sid)
    act_nlp.run(fake_context, sid)
    assert fake_db.transcript_versions[-1]["stats"]["asr_route"]["detected_variant"] == "de-AT"


def test_fusion_of_an_old_asr_document_gets_a_default_route(fake_db, fake_context, tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    fake_context.settings = _settings(monkeypatch)
    sid = _source(fake_db, fake_context, tmp_path)
    act_asr.run_diarize(fake_context, sid)
    words = [{"text": "Hallo.", "start": 0.0, "end": 0.4, "prob": 0.9}]
    akey = act_asr.asr_key_for("audio/t.wav", "de", [], fake_context.settings.asr_model_de, fake_context.settings)
    fake_context.store.put_json("derived", akey, {"words": words, "model_id": "m", "variant": "de", "beta": False})
    act_nlp.run(fake_context, sid)
    route = fake_db.transcript_versions[-1]["stats"]["asr_route"]
    assert route["variant"] == "de" and route["model_id"] == "m" and route["routing_reason"] == "profile"
