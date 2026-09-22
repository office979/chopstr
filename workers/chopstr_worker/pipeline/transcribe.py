"""Transkription mit Wort-Zeitstempeln und Sprecherzuordnung (DACH-optimiert).

- Hochdeutsch (DE/AT): Modell aus ``ASR_MODEL_DE`` (CTranslate2 für faster-whisper)
- Schweizerdeutsch: Modell aus ``ASR_MODEL_CH`` (Beta, Flag ``beta=True`` im Ergebnis)
- Fallback ``gladia-eu``: nur wenn ``GLADIA_BASE_URL`` gesetzt ist und der Residency-Guard den Host erlaubt
- Lange Dateien werden in Fenster (Default 600 s) mit Überlappung (20 s) transkribiert und an der
  Grenze über Wortzeiten zusammengeführt (``merge_windows``, deterministisch, ohne Modell testbar).
- Marken-Wörterbuch: als hotwords + Nachkorrektur (``apply_brand_vocab``)
- Zahlen-Normalisierung (``normalize_numbers``) läuft ERST nach dem Alignment (Sprecher pro Wort),
  damit die Wortzeiten unverändert bleiben.
- Diarisierung: pyannote (lazy), exclusive_speaker_diarization; Sprecher pro Wort per MEHRHEIT
  über die Wortdauer (``assign_speakers``, reine Funktion).

faster-whisper, pyannote und torch werden nur innerhalb von Funktionen importiert.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import config, residency
from . import dach_nlp

log = logging.getLogger("chopstr.asr")

VARIANTS = ("de", "de-CH")
LOW_CONF_THRESHOLD = 0.5
_DEFAULT_DIARIZER = "pyannote/speaker-diarization-community-1"  # TODO: per DIARIZER_MODEL bestätigen


class TranscribeError(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    start: float
    end: float
    prob: float
    speaker: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranscriptResult:
    words: list[dict]
    model_id: str
    variant: str
    provider: str = "selfhost-eu"
    beta: bool = False
    windows: int = 1
    duration_s: float = 0.0
    compute_seconds: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------------------------
# Reine Funktionen (ohne Modell testbar)
# ---------------------------------------------------------------------------------------------
def plan_windows(duration_s: float, window_s: float = 600.0, overlap_s: float = 20.0) -> list[tuple[float, float]]:
    """Fensterplan [(start, end), ...]. Letztes Fenster endet bei ``duration_s``."""
    if duration_s <= 0:
        return [(0.0, 0.0)]
    if window_s <= overlap_s:
        raise ValueError("window_s muss größer als overlap_s sein")
    if duration_s <= window_s:
        return [(0.0, float(duration_s))]
    out, start = [], 0.0
    while True:
        end = min(start + window_s, duration_s)
        out.append((round(start, 3), round(end, 3)))
        if end >= duration_s:
            break
        start = end - overlap_s
    return out


def _mid(w: dict) -> float:
    return (float(w["start"]) + float(w["end"])) / 2.0


def _best_cut(words_a: list[dict], lo: float, hi: float) -> float:
    """Schnittpunkt im Überlappungsbereich [lo, hi]: Mitte der längsten Pause, sonst Mitte des Bereichs."""
    best_gap, best_t = -1.0, (lo + hi) / 2.0
    inside = [w for w in words_a if lo <= _mid(w) <= hi]
    for a, b in zip(inside, inside[1:]):
        gap = float(b["start"]) - float(a["end"])
        if gap > best_gap:
            best_gap, best_t = gap, (float(a["end"]) + float(b["start"])) / 2.0
    return best_t


def merge_windows(results: list[tuple[float, float, list[dict]]]) -> list[dict]:
    """Führt Fensterergebnisse ``[(win_start, win_end, words_absolute), ...]`` zusammen.

    Im Überlappungsbereich zweier Fenster wird an der längsten Pause des ersten Fensters geschnitten:
    Wörter des ersten Fensters mit Mitte vor dem Schnitt bleiben, Wörter des zweiten Fensters mit Mitte
    danach kommen dazu. Zeitlich stark überlappende Dubletten an der Naht werden verworfen.
    Deterministisch, keine Modellabhängigkeit.
    """
    if not results:
        return []
    results = sorted(results, key=lambda r: r[0])
    merged: list[dict] = list(results[0][2])
    prev_end = results[0][1]
    for win_start, win_end, words in results[1:]:
        if win_start >= prev_end:
            merged.extend(words)
            prev_end = win_end
            continue
        cut = _best_cut(merged, win_start, prev_end)
        merged = [w for w in merged if _mid(w) < cut]
        incoming = [w for w in words if _mid(w) >= cut]
        if merged and incoming:
            last = merged[-1]
            while incoming and _overlap_ratio(last, incoming[0]) > 0.5:
                incoming.pop(0)
        merged.extend(incoming)
        prev_end = win_end
    return merged


def _overlap_ratio(a: dict, b: dict) -> float:
    inter = max(0.0, min(float(a["end"]), float(b["end"])) - max(float(a["start"]), float(b["start"])))
    shorter = max(1e-6, min(float(a["end"]) - float(a["start"]), float(b["end"]) - float(b["start"])))
    return inter / shorter


def _edit_distance_le1(a: str, b: str) -> bool:
    """True, wenn sich a und b um höchstens eine Einfügung, Löschung oder Ersetzung unterscheiden."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    skipped = False
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


FUZZY_MIN_LEN = 6


def apply_brand_vocab(words: list[dict], vocab: list[str]) -> list[dict]:
    """Nachkorrektur auf Markenschreibweise: exakt (case-insensitiv, ohne Sonderzeichen) oder konservativ
    fuzzy (ein Tippfehler, gleicher Wortanfang, nur für Vokabeln ab 6 Zeichen)."""
    lookup = {re.sub(r"\W", "", v.lower()): v for v in vocab if v and v.strip()}
    if not lookup:
        return words
    fuzzy = [(k, v) for k, v in lookup.items() if len(k) >= FUZZY_MIN_LEN]
    for w in words:
        raw = str(w["text"])
        key = re.sub(r"\W", "", raw.lower())
        if not key:
            continue
        hit = lookup.get(key)
        if hit is None and len(key) >= FUZZY_MIN_LEN:
            for k, v in fuzzy:
                if k[:3] == key[:3] and _edit_distance_le1(k, key):
                    hit = v
                    break
        if hit is not None:
            trailing = re.findall(r"[.,!?;:]+$", raw)
            w["text"] = hit + (trailing[0] if trailing else "")
    return words


def normalize_numbers(words: list[dict]) -> list[dict]:
    """Dezimalkomma und Prozentzeichen; NUR nach dem Alignment aufrufen (ändert keine Zeiten)."""
    for w in words:
        w["text"] = dach_nlp.de_number(str(w["text"]))
    return words


def assign_speakers(words: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    """Sprecher pro Wort per Mehrheit über die Wortdauer. ``turns``: [(start, end, speaker), ...].

    Ein Wort bekommt den Sprecher, dessen Turns die größte Überlappung mit [start, end] haben.
    Ohne Überlappung: nächstgelegener Turn. Ohne Turns: ``speaker`` bleibt None.
    """
    if not turns:
        return words
    turns = sorted(turns, key=lambda t: (t[0], t[1]))
    j = 0
    for w in words:
        ws, we = float(w["start"]), float(w["end"])
        if we <= ws:
            we = ws + 1e-3
        while j < len(turns) - 1 and turns[j][1] < ws:
            j += 1
        share: dict[str, float] = {}
        k = j
        while k < len(turns) and turns[k][0] < we:
            ts, te, spk = turns[k]
            inter = max(0.0, min(we, te) - max(ws, ts))
            if inter > 0:
                share[spk] = share.get(spk, 0.0) + inter
            k += 1
        if share:
            w["speaker"] = max(share.items(), key=lambda kv: (kv[1], kv[0]))[0]
        else:
            w["speaker"] = _nearest(turns, (ws + we) / 2)
    return words


def _nearest(turns: list[tuple[float, float, str]], t: float) -> str:
    return min(turns, key=lambda x: min(abs(x[0] - t), abs(x[1] - t)))[2]


def confidence_stats(words: list[dict], threshold: float = LOW_CONF_THRESHOLD) -> dict[str, Any]:
    n = len(words)
    if n == 0:
        return {"word_count": 0, "mean_prob": 0.0, "low_conf_ratio": 0.0, "low_conf_count": 0, "speakers": []}
    probs = [float(w.get("prob", 1.0)) for w in words]
    low = sum(1 for p in probs if p < threshold)
    speakers = sorted({w["speaker"] for w in words if w.get("speaker")})
    return {
        "word_count": n,
        "mean_prob": round(sum(probs) / n, 4),
        "low_conf_ratio": round(low / n, 4),
        "low_conf_count": low,
        "speakers": speakers,
    }


def to_json(words: list[Word]) -> list[dict]:
    return [w.to_dict() for w in words]


# ---------------------------------------------------------------------------------------------
# Modellgestützte Funktionen (lazy imports)
# ---------------------------------------------------------------------------------------------
def _device(s: config.Settings) -> tuple[str, str]:
    device, compute = s.asr_device or "auto", s.asr_compute or "int8"
    if device == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    if device == "cpu" and compute in {"int8_float16", "float16"}:
        compute = "int8"
    return device, compute


_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


def load_model(model_id: str, s: config.Settings | None = None):
    """faster-whisper-Modell (gecacht pro Prozess)."""
    s = s or config.settings()
    device, compute = _device(s)
    key = (model_id, device, compute)
    if key not in _MODEL_CACHE:
        from faster_whisper import WhisperModel

        _MODEL_CACHE[key] = WhisperModel(model_id, device=device, compute_type=compute)
    return _MODEL_CACHE[key]


def _read_wav(audio_path: str):
    import wave

    import numpy as np

    with wave.open(audio_path, "rb") as wf:
        sr = wf.getframerate()
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise TranscribeError("Audio muss 16-bit Mono PCM sein (siehe ingest.extract_audio)")
        x = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return sr, x


def transcribe_window(model, audio, sr: int, start: float, end: float, hotwords: str | None) -> list[dict]:
    """Ein Fenster transkribieren; Wortzeiten absolut (um ``start`` verschoben)."""
    a, b = int(start * sr), int(end * sr)
    chunk = audio[a:b]
    if len(chunk) == 0:
        return []
    segments, _info = model.transcribe(
        chunk,
        language="de",
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        hotwords=hotwords or None,
        condition_on_previous_text=False,
    )
    out: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            text = str(w.word).strip()
            if not text:
                continue
            out.append(
                Word(text, round(float(w.start) + start, 3), round(float(w.end) + start, 3), float(w.probability)).to_dict()
            )
    return out


def transcribe(
    audio_path: str,
    variant: str = "de",
    brand_vocab: list[str] | None = None,
    s: config.Settings | None = None,
    fallback: str | None = None,
    duration_s: float | None = None,
) -> TranscriptResult:
    """Routing: ``de`` | ``de-CH`` (Beta) | ``fallback="gladia-eu"``."""
    s = s or config.settings()
    brand_vocab = [v for v in (brand_vocab or []) if v]
    if variant not in VARIANTS:
        raise TranscribeError(f"Unbekannte ASR-Variante {variant!r} (erlaubt: {', '.join(VARIANTS)})")
    if fallback == "gladia-eu":
        return _transcribe_gladia(audio_path, brand_vocab, s)
    if fallback:
        raise TranscribeError(f"Unbekannter ASR-Fallback {fallback!r}")

    model_id = s.asr_model_for(variant)
    if not model_id:
        env = "ASR_MODEL_CH" if variant == "de-CH" else "ASR_MODEL_DE"
        raise TranscribeError(f"Kein ASR-Modell für Variante {variant} konfiguriert ({env} setzen)")

    t0 = time.monotonic()
    model = load_model(model_id, s)
    sr, audio = _read_wav(audio_path)
    total = duration_s if duration_s is not None else len(audio) / float(sr)
    windows = plan_windows(total, s.asr_window_s, s.asr_overlap_s)
    hotwords = " ".join(brand_vocab) if brand_vocab else None
    results = []
    for ws, we in windows:
        results.append((ws, we, transcribe_window(model, audio, sr, ws, we, hotwords)))
        log.info("asr window %.0f..%.0f done (%d words)", ws, we, len(results[-1][2]))
    words = merge_windows(results)
    words = apply_brand_vocab(words, brand_vocab)
    stats = confidence_stats(words)
    return TranscriptResult(
        words=words,
        model_id=model_id,
        variant=variant,
        provider="selfhost-eu",
        beta=(variant == "de-CH"),
        windows=len(windows),
        duration_s=round(total, 3),
        compute_seconds=round(time.monotonic() - t0, 3),
        stats=stats,
    )


def _transcribe_gladia(audio_path: str, brand_vocab: list[str], s: config.Settings) -> TranscriptResult:
    """Fallback über Gladia (EU-Endpoint). Nur mit GLADIA_BASE_URL und erlaubtem Host.

    TODO: Antwortformat gegen die aktuelle Gladia-API prüfen (Upload, pre-recorded, Polling)."""
    if not s.gladia_base_url:
        raise TranscribeError(
            "Fallback gladia-eu ist nicht freigeschaltet: GLADIA_BASE_URL fehlt. "
            "Fallback muss pro Workspace freigegeben und der Host per Residency-Allowlist erlaubt sein."
        )
    residency.assert_eu_host(s.gladia_base_url, s)
    if not s.gladia_api_key:
        raise TranscribeError("GLADIA_API_KEY fehlt")
    base = s.gladia_base_url.rstrip("/")
    headers = {"x-gladia-key": s.gladia_api_key}
    t0 = time.monotonic()
    with residency.guarded_client(s, timeout=600) as client:
        with open(audio_path, "rb") as f:
            up = client.post(f"{base}/v2/upload", headers=headers, files={"audio": ("audio.wav", f, "audio/wav")})
        up.raise_for_status()
        audio_url = up.json().get("audio_url")
        body = {
            "audio_url": audio_url,
            "language": "de",
            "diarization": False,
            "custom_vocabulary": brand_vocab or None,
        }
        job = client.post(f"{base}/v2/pre-recorded", headers=headers, json=body)
        job.raise_for_status()
        result_url = job.json().get("result_url")
        if not result_url:
            raise TranscribeError("Gladia: keine result_url erhalten")
        residency.assert_eu_host(result_url, s)
        data = None
        for _ in range(720):
            r = client.get(result_url, headers=headers)
            r.raise_for_status()
            data = r.json()
            if data.get("status") in {"done", "error"}:
                break
            time.sleep(5)
    if not data or data.get("status") != "done":
        raise TranscribeError("Gladia: Transkription nicht abgeschlossen")
    words: list[dict] = []
    for utt in data.get("result", {}).get("transcription", {}).get("utterances", []):
        for w in utt.get("words", []):
            words.append(Word(str(w.get("word", "")).strip(), float(w["start"]), float(w["end"]), float(w.get("confidence", 1.0))).to_dict())
    words = apply_brand_vocab(words, brand_vocab)
    return TranscriptResult(
        words=words,
        model_id="gladia",
        variant="de",
        provider="gladia-eu",
        beta=False,
        windows=1,
        duration_s=float(words[-1]["end"]) if words else 0.0,
        compute_seconds=round(time.monotonic() - t0, 3),
        stats=confidence_stats(words),
    )


_DIARIZER_CACHE: dict[str, Any] = {}


def load_diarizer(s: config.Settings | None = None):
    s = s or config.settings()
    model_id = s.diarizer_model or _DEFAULT_DIARIZER
    if model_id not in _DIARIZER_CACHE:
        import torch
        from pyannote.audio import Pipeline

        if not s.hf_token:
            raise TranscribeError("HF_TOKEN fehlt (Nutzungsbedingungen des pyannote-Modells akzeptieren)")
        pipe = Pipeline.from_pretrained(model_id, token=s.hf_token)
        if pipe is None:
            raise TranscribeError(f"Diarisierungsmodell {model_id} konnte nicht geladen werden")
        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
        _DIARIZER_CACHE[model_id] = pipe
    return _DIARIZER_CACHE[model_id]


def diarize(
    audio_path: str,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    s: config.Settings | None = None,
) -> dict[str, Any]:
    """Liefert ``{"turns": [[start, end, speaker], ...], "model_id": ..., "compute_seconds": ...}``.

    DSGVO: anonyme Labels (SPEAKER_00 ...), keine projektübergreifende Stimm-Wiedererkennung."""
    s = s or config.settings()
    t0 = time.monotonic()
    pipe = load_diarizer(s)
    kwargs = {}
    if min_speakers:
        kwargs["min_speakers"] = int(min_speakers)
    if max_speakers:
        kwargs["max_speakers"] = int(max_speakers)
    out = pipe(audio_path, **kwargs)
    annotation = getattr(out, "exclusive_speaker_diarization", None)
    if annotation is None:  # ältere pyannote-Versionen liefern die Annotation direkt
        annotation = getattr(out, "speaker_diarization", out)
    turns = [[round(float(seg.start), 3), round(float(seg.end), 3), str(spk)] for seg, _track, spk in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda t: (t[0], t[1]))
    return {
        "turns": turns,
        "model_id": s.diarizer_model or _DEFAULT_DIARIZER,
        "speakers": sorted({t[2] for t in turns}),
        "compute_seconds": round(time.monotonic() - t0, 3),
    }


__all__ = [
    "LOW_CONF_THRESHOLD",
    "VARIANTS",
    "TranscribeError",
    "TranscriptResult",
    "Word",
    "apply_brand_vocab",
    "assign_speakers",
    "confidence_stats",
    "diarize",
    "load_diarizer",
    "load_model",
    "merge_windows",
    "normalize_numbers",
    "plan_windows",
    "to_json",
    "transcribe",
    "transcribe_window",
]
