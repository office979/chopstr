"""Echte CPU-Transkription mit faster-whisper (Marker ``network``: lädt das Modell beim ersten Lauf).

Sprache kommt aus macOS ``say -v Anna`` (deutsche Stimme), ffmpeg wandelt in 16-kHz-Mono-WAV,
``pipeline.transcribe.transcribe`` läuft mit ``ASR_DEVICE=cpu`` und ``ASR_COMPUTE=int8``.
Ohne ``faster_whisper``, ohne ``say`` oder ohne ffmpeg wird der Test übersprungen; ohne Netz beim
ersten Lauf schlägt er mit einer klaren Meldung fehl (Modell-Download ist Teil des Tests).
Modell: ``ASR_MODEL_DE`` aus der Umgebung, sonst die in der README verifizierte ID.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess

import pytest

from chopstr_worker import config
from chopstr_worker.pipeline import transcribe as asr

pytestmark = pytest.mark.network

# Auf Hugging Face bestätigt (Dateien model.bin, config.json, tokenizer.json, vocabulary.json):
# int8-CTranslate2-Konvertierung von primeline/whisper-large-v3-turbo-german, Apache-2.0.
VERIFIED_MODEL_DE = "cstr/whisper-large-v3-turbo-german-int8_float32"
SENTENCE = "Wir haben in unserer Branche vierzig Prozent Marge verloren, weil das Preismodell falsch war."

requires_asr = pytest.mark.skipif(importlib.util.find_spec("faster_whisper") is None, reason="faster_whisper nicht installiert")
requires_say = pytest.mark.skipif(shutil.which("say") is None, reason="macOS say nicht verfügbar")
requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")


@requires_asr
@requires_say
@requires_ffmpeg
def test_real_transcription_on_cpu(tmp_path, monkeypatch):
    aiff = tmp_path / "satz.aiff"
    wav = tmp_path / "satz16k.wav"
    subprocess.run(["say", "-v", "Anna", "-o", str(aiff), SENTENCE], check=True, capture_output=True)
    subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-v", "error", "-i", str(aiff), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True,
    )  # fmt: skip

    model_id = os.environ.get("ASR_MODEL_DE", "").strip() or VERIFIED_MODEL_DE
    monkeypatch.setenv("ASR_MODEL_DE", model_id)
    monkeypatch.setenv("ASR_DEVICE", "cpu")
    monkeypatch.setenv("ASR_COMPUTE", "int8")
    s = config.reload()

    try:
        result = asr.transcribe(str(wav), variant="de", s=s)
    except Exception as exc:  # Download oder Laden fehlgeschlagen
        name = exc.__class__.__name__
        if any(k in name.lower() for k in ("connection", "timeout", "http", "hfhub", "repository", "network", "entrynotfound")):
            pytest.fail(f"Modell {model_id} konnte nicht geladen werden (kein Netz oder falsche ID): {name}: {str(exc)[:200]}")
        raise

    text = " ".join(str(w["text"]) for w in result.words).lower()
    assert result.model_id == model_id and result.provider == "selfhost-eu" and result.windows == 1
    assert result.stats["word_count"] >= 8, text
    assert re.search(r"(vierzig|40)\s*(prozent|%)", text), text
    assert "preismodell" in text, text
    assert result.compute_seconds > 0
