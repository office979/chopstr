"""Stufe 1 der hybriden Clip-Erkennung: billige Signale über die ganze Datei, bevor das LLM teuer wird.

Ergebnis: Heatmap in 1-s-Bins plus Seed-Zeitpunkte für die LLM-Stufe.
Signale: Audio (RMS-Energie, Spectral Flux), Text (deutsche Diskursmarker, Fragen, Zahlen),
optional Lachen/Applaus als externer Hook.
"""

from __future__ import annotations

import re
import wave

import numpy as np

DISCOURSE_MARKERS = [
    "das entscheidende", "der eigentliche grund", "und jetzt kommt", "ehrlich gesagt", "der fehler war",
    "das hat alles verändert", "was die wenigsten wissen", "der punkt ist", "ganz ehrlich", "stell dir vor",
    "stellen sie sich vor", "die wahrheit ist", "das wichtigste", "zum beispiel", "konkret heißt das",
    "wir haben damals", "ich war", "der moment, als", "und dann", "das problem ist", "das heißt konkret",
    "was ich gelernt habe", "mein größter fehler", "die zahl ist",
]  # fmt: skip

MARKER_HORIZON_BINS = 20
QUESTION_HORIZON_BINS = 15


def read_wav_mono(wav_path: str) -> tuple[int, np.ndarray]:
    with wave.open(wav_path, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        raw = raw.reshape(-1, ch).mean(axis=1)
    return sr, raw


def audio_heatmap(wav_path: str, bin_s: float = 1.0) -> np.ndarray:
    sr, x = read_wav_mono(wav_path)
    hop = max(1, int(sr * bin_s))
    n = len(x) // hop
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames**2).mean(axis=1) + 1e-9)
    spec = np.abs(np.fft.rfft(frames * np.hanning(hop), axis=1))
    flux = np.r_[0, np.maximum(spec[1:] - spec[:-1], 0).sum(axis=1)] if n > 1 else np.zeros(n)

    def z(v):
        return (v - np.median(v)) / (np.std(v) + 1e-9)

    return np.clip(0.6 * z(rms) + 0.4 * z(flux), -3, 3).astype(np.float32)


def text_heatmap(words: list[dict], n_bins: int, bin_s: float = 1.0) -> np.ndarray:
    h = np.zeros(max(n_bins, 1), dtype=np.float32)
    if not words:
        return h
    text = " ".join(str(w["text"]).lower() for w in words)
    starts, pos = [], 0
    for w in words:
        starts.append((pos, float(w["start"])))
        pos += len(str(w["text"])) + 1

    def bin_of(t: float) -> int:
        return min(max(int(t / bin_s), 0), len(h) - 1)

    for m in DISCOURSE_MARKERS:
        for hit in re.finditer(re.escape(m), text):
            t = next((st for p, st in reversed(starts) if p <= hit.start()), 0.0)
            b = bin_of(t)
            h[b : b + MARKER_HORIZON_BINS] += 1.0
    for w in words:
        b = bin_of(float(w["start"]))
        if str(w["text"]).endswith("?"):
            h[b : b + QUESTION_HORIZON_BINS] += 0.5
        if re.search(r"\d", str(w["text"])):
            h[b] += 0.5
    return h


def seeds(heat: np.ndarray, top_k: int = 25, min_gap_s: int = 45) -> list[int]:
    """Top-Zeitpunkte mit Mindestabstand (Non-Maximum-Suppression)."""
    order = np.argsort(-heat, kind="stable")
    chosen: list[int] = []
    for t in order:
        if all(abs(int(t) - c) >= min_gap_s for c in chosen):
            chosen.append(int(t))
        if len(chosen) >= top_k:
            break
    return sorted(chosen)


def combined(wav_path: str, words: list[dict], laughter: np.ndarray | None = None, audio: np.ndarray | None = None) -> np.ndarray:
    """Audio und Text zu gleichen Teilen. ``audio`` erlaubt es, den bereits berechneten Audioanteil
    hereinzureichen, statt ihn ein zweites Mal aus der Datei zu lesen."""
    a = audio if audio is not None else audio_heatmap(wav_path)
    t = text_heatmap(words, len(a))
    h = 0.5 * a + 0.5 * t
    if laughter is not None and len(laughter) == len(h):
        h = h + 0.8 * laughter  # Lachen/Applaus markiert Pointen (Humor bleibt Mensch-Review)
    return h.astype(np.float32)


def to_payload(heat: np.ndarray, bin_s: float = 1.0, top_k: int = 25, audio: np.ndarray | None = None) -> dict:
    """JSON-taugliche Darstellung für den Storage.

    ``audio`` ist der reine Audioanteil ohne Textmischung. Die Bewertung braucht ihn getrennt: Die
    Textsignale stecken bereits in der Rubrik, und sie ein zweites Mal über die Heatmap einzurechnen
    wäre eine Doppelzählung.
    """
    out = {
        "bin_s": bin_s,
        "n_bins": int(len(heat)),
        "values": [round(float(v), 4) for v in heat],
        "seeds": seeds(heat, top_k=top_k),
    }
    if audio is not None:
        out["audio_values"] = [round(float(v), 4) for v in audio]
    return out


__all__ = ["DISCOURSE_MARKERS", "audio_heatmap", "combined", "read_wav_mono", "seeds", "text_heatmap", "to_payload"]
