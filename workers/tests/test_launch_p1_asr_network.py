"""Lane P1, Ausfall im Produktionspfad (Baseline Phase 0): Marken-Wörterbuch als Decoder-Hotwords verschluckt Sätze.

Befund: Im lokalen Worker fehlten in ``c_debatte_viertagewoche`` 37 Wörter am Stück (73,5 bis 86,3 s), darunter die
Bedingung „Das funktioniert nur, wenn man die Arbeitszeit pro Tag erhöht …“ (Regel 2). Ursache: das Markenprofil
hatte ``brand_vocab = ["chopstr", "PLACEMedia"]``, ``transcribe`` gab sie als ``hotwords`` an faster-whisper, und
faster-whisper 1.2.1 setzt Hotwords als Prompt vor jeden 30-s-Abschnitt (``WhisperModel.get_prompt``). Die VAD war
es nicht (gleiche Sprachsegmente auf Worker- und Original-WAV). Messung an allen drei Dateien:
``docs/decisions/010-asr-routing.md``.

Material und Modell liegen nicht im Repo (``workers/eval/runs/`` ist in .gitignore, das Modell im HF-Cache); fehlen
sie, wird mit Grund übersprungen. Erste 120 s reichen, um den Ausfall nachzustellen (geprüft: 200 statt 237 Wörter).
"""

from __future__ import annotations

import importlib.util
import shutil
import wave
from pathlib import Path

import pytest

from chopstr_worker import config, ingest
from chopstr_worker.pipeline import transcribe as asr

pytestmark = pytest.mark.network

MODEL = "cstr/whisper-large-v3-turbo-german-int8_float32"
MATERIAL = Path(__file__).resolve().parents[1] / "eval/runs/testmaterial/c_debatte_viertagewoche/c_debatte_viertagewoche.mp4"
VOCAB = ["chopstr", "PLACEMedia"]
EXCERPT_S = 120.0


def _model_cached() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(MODEL, "model.bin"), str)
    except Exception:
        return False


requires_material = pytest.mark.skipif(
    importlib.util.find_spec("faster_whisper") is None or shutil.which("ffmpeg") is None or not MATERIAL.is_file() or not _model_cached(),
    reason="faster_whisper, ffmpeg, Testmaterial c_debatte_viertagewoche (eval/runs, nicht im Repo) oder Modell im HF-Cache fehlt",
)


@pytest.fixture(scope="module")
def excerpt(tmp_path_factory) -> str:
    """Wie der Worker: 16-kHz-Mono aus dem MP4 (AAC), dann die ersten 120 s."""
    work = tmp_path_factory.mktemp("c_debatte")
    full = ingest.extract_audio(MATERIAL, work / "audio16k.wav")
    out = work / "excerpt.wav"
    with wave.open(full, "rb") as src, wave.open(str(out), "wb") as dst:
        dst.setparams(src.getparams())
        dst.writeframes(src.readframes(int(EXCERPT_S * src.getframerate())))
    return str(out)


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("ASR_MODEL_DE", MODEL)
    monkeypatch.setenv("ASR_DEVICE", "cpu")
    monkeypatch.setenv("ASR_COMPUTE", "int8")
    monkeypatch.delenv("ASR_AUTO_ROUTE", raising=False)
    return config.reload()


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


@requires_material
def test_cause_hotwords_in_the_decoder_swallow_the_condition(excerpt, settings):
    """Ursache: derselbe Abschnitt mit und ohne Hotwords; mit Hotwords fehlt die Bedingung."""
    model = asr.load_model(MODEL, settings)
    sr, audio = asr._read_wav(excerpt)
    plain = _text(asr.transcribe_window(model, audio, sr, 0.0, EXCERPT_S, None))
    hot = _text(asr.transcribe_window(model, audio, sr, 0.0, EXCERPT_S, " ".join(VOCAB)))
    assert "nur, wenn" in plain and "Arbeitszeit" in plain
    assert "Arbeitszeit" not in hot, "faster-whisper verschluckt die Stelle mit Hotwords nicht mehr; Notiz 010 prüfen"


@requires_material
def test_fix_default_path_keeps_the_condition_with_brand_vocab(excerpt, settings):
    """Fix: Standardpfad mit Marken-Wörterbuch (ohne ASR_AUTO_ROUTE) hat die Stelle; das Wörterbuch wirkt nur nach."""
    result = asr.transcribe(excerpt, "de", brand_vocab=VOCAB, s=settings)
    text = _text(result.words)
    assert "Das funktioniert nur, wenn man die Arbeitszeit pro Tag erhöht" in text
    assert "Ohne neuen Schichtplan würde ich es keinem Betrieb raten." in text
    assert result.route["hotwords"] == {"terms": 2, "decode": False}
    gaps = [b["start"] - a["end"] for a, b in zip(result.words, result.words[1:])]
    assert max(gaps) < 5.0  # keine Lücke wie 73,5 bis 86,3 s
