"""Stufe 1 der hybriden Clip-Erkennung: billige Signale über die ganze Datei, bevor das LLM teuer wird.

Ergebnis: Heatmap in 1-s-Bins plus Seed-Zeitpunkte für die LLM-Stufe.
Signale: Audio (RMS-Energie, Spectral Flux), Text (deutsche Diskursmarker, Fragen, Zahlen),
optional Lachen/Applaus als externer Hook.
"""

from __future__ import annotations

import math
import re
import wave
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .. import editorial

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


# Auflösung der Wellenform für die Zeitleiste. 25 Werte je Sekunde: fein genug, um eine Sprechpause
# von einer Zehntelsekunde zu sehen, und grob genug, dass ein zehnminütiges Video unter hundert
# Kilobyte bleibt. Feiner bringt nichts, weil die Anzeige ohnehin nur ein paar hundert Bildpunkte
# breit ist.
WELLENFORM_BIN_S = 0.04


def wellenform(wav_path: str, bin_s: float = WELLENFORM_BIN_S) -> dict:
    """Spitzenwerte der Lautstärke über die Zeit, für die Darstellung in der Zeitleiste.

    Gemessen wird der Höchstwert je Abschnitt, nicht der Durchschnitt: ein kurzer lauter Einsatz
    soll sichtbar sein, und genau an seinem Rand will jemand schneiden. Der Durchschnitt würde ihn
    verschleifen.

    Die Werte sind 0 bis 255, damit die Datei klein bleibt; für eine Darstellung von ein paar
    hundert Bildpunkten Höhe ist das mehr als genug.
    """
    sr, x = read_wav_mono(wav_path)
    hop = max(1, int(sr * bin_s))
    n = len(x) // hop
    if n == 0:
        return {"bin_s": bin_s, "dauer_s": 0.0, "werte": []}
    frames = np.abs(x[: n * hop].reshape(n, hop)).max(axis=1)
    # Auf den lautesten Abschnitt beziehen: eine leise Aufnahme soll nicht als flache Linie
    # erscheinen, nur weil niemand ins Mikrofon geschrien hat.
    spitze = float(frames.max()) or 1.0
    werte = np.clip(frames / spitze * 255.0, 0, 255).astype(np.uint8)
    return {"bin_s": bin_s, "dauer_s": round(len(x) / sr, 3), "werte": [int(v) for v in werte]}


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

    ``laughter_values`` ist der eine Schlüssel für Lachen je Bin (gelesen von ``payoff_search`` und
    ``trim_plan``). Lachen wird noch nicht berechnet (Register: ``audio.merkmale.lachen`` not_implemented),
    deshalb steht dort eine leere Liste; leer heißt für beide Leser „kein Lachen bekannt“.
    """
    out = {
        "bin_s": bin_s,
        "n_bins": int(len(heat)),
        "values": [round(float(v), 4) for v in heat],
        "seeds": seeds(heat, top_k=top_k),
        "laughter_values": [],
    }
    if audio is not None:
        out["audio_values"] = [round(float(v), 4) for v in audio]
    return out


# -- Text-Heatmap v2 (Launch Phase 2, Schalter implementation.heat.text_v2 und Regel heat.text_v2) ----------
# Befund der Inventur: der Textanteil von ``combined`` sind rohe Zähler (0,5 je Frage oder Zahl, 1,0 je Marker),
# gemischt mit einem z-normierten Audioanteil; die Marker greifen auf wenigen Sätzen, ein ruhig vorgetragenes
# Kernargument fällt deshalb gegen jede laute Stelle ab. v2 ergänzt Überraschung, Negation einer Erwartung,
# Zahlen mit Einheit, Stakes (Geld, Zeit, Verlust, Risiko), Reaktionen des Gegenübers und Zitate, normiert den
# Textanteil wie den Audioanteil und mischt mit ``heat.text_weight``. Die Wortlisten stehen mit Herkunft in der
# Policy (Abschnitt ``heat``); hier steht nur das Verfahren.

HEAT_SWITCH = "heat.text_v2"
HEAT_MARKER_KEYS = (
    "surprise", "expectation_negation", "stakes_money", "stakes_time", "stakes_loss", "stakes_risk", "reaction", "quote",
)  # fmt: skip
TEXT_V2_HORIZON_BINS = 10  # wie weit ein Treffer nachwirkt (die Aussage, die er einleitet)
REACTION_MAX_WORDS = 3  # ein Einwurf des Gegenübers ist höchstens so lang
REACTION_LOOKBACK_BINS = 10  # eine Reaktion markiert die Sekunden davor (worauf reagiert wird)
NUMBER_WORDS = frozenset({
    "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf", "zwanzig", "dreißig",
    "vierzig", "fünfzig", "hundert", "tausend", "doppelt", "halb", "hälfte",
})  # fmt: skip
_PUNCT = "\"'„“”‚‘’»«()[]{}.,;:!?…-"


def _core(token: str) -> str:
    return str(token).lower().strip(_PUNCT)


def text_heat_settings(policy: editorial.Policy | None) -> dict[str, Any] | None:
    """Einstellungen der Text-Heatmap v2 aus dem Abschnitt ``heat`` oder ``None``.

    ``None`` in Fassung 1, ohne Abschnitt, mit Schalter ``implementation.heat.text_v2`` aus oder mit der Regel
    ``heat.text_v2`` auf false (Rollback: Heatmap wie gespeichert). Rückgabe ``{text_weight, markers, units}``;
    ``markers`` hat genau die Schlüssel aus ``HEAT_MARKER_KEYS``. Ein unbrauchbarer Wert scheitert laut."""
    if policy is None or policy.version < 2 or "heat" not in policy.roh:
        return None
    name = f"clip_policy_v{policy.version}"
    raw = policy.roh["heat"]
    impl = policy.roh.get("implementation") or {}
    switch = (impl.get("heat") or {}).get("text_v2") if isinstance(impl.get("heat"), dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("text_v2"), bool):
        raise editorial.PolicyError(f"{name}: heat.text_v2 ist true oder false.")
    if switch is not True or raw["text_v2"] is not True:
        return None
    try:
        weight = float(raw["text_weight"])
    except (KeyError, TypeError, ValueError):
        raise editorial.PolicyError(f"{name}: heat.text_weight fehlt oder ist keine Zahl.") from None
    if not 0.0 <= weight <= 1.0:
        raise editorial.PolicyError(f"{name}: heat.text_weight liegt zwischen 0 und 1.")
    markers = raw.get("markers")
    if not isinstance(markers, dict) or set(markers) != set(HEAT_MARKER_KEYS):
        raise editorial.PolicyError(f"{name}: heat.markers braucht genau die Schlüssel {', '.join(HEAT_MARKER_KEYS)}.")
    table = {k: tuple(str(x).lower() for x in (markers[k] or ()) if str(x).strip()) for k in HEAT_MARKER_KEYS}
    empty = [k for k, v in table.items() if not v]
    if empty:
        raise editorial.PolicyError(f"{name}: heat.markers ohne Einträge für {', '.join(empty)}.")
    units = tuple(_core(x) for x in (raw.get("units") or ()) if _core(x))
    if not units:
        raise editorial.PolicyError(f"{name}: heat.units braucht mindestens eine Einheit.")
    return {"text_weight": weight, "markers": table, "units": units}


def _phrase_hits(cores: list[str], phrase: str) -> list[int]:
    toks = [c for c in (_core(x) for x in phrase.split()) if c]
    if not toks:
        return []
    return [k for k in range(len(cores) - len(toks) + 1) if cores[k : k + len(toks)] == toks]


def _turns(words: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
    """Redebeiträge als Wortbereiche ``(von, bis)``: aufeinanderfolgende Wörter desselben Sprechers."""
    out: list[tuple[int, int]] = []
    a = 0
    for i in range(1, len(words) + 1):
        if i == len(words) or words[i].get("speaker") != words[a].get("speaker"):
            out.append((a, i - 1))
            a = i
    return out


def text_heatmap_v2(
    words: Sequence[Mapping[str, Any]],
    n_bins: int,
    cfg: Mapping[str, Any],
    bin_s: float = 1.0,
    laughter: Sequence[float] | None = None,
) -> tuple[np.ndarray, dict[str, int]]:
    """Roher Textanteil v2 je Bin und die Trefferzahl je Merkmal.

    Grundlage ist ``text_heatmap`` (Diskursmarker, Fragen, Zahlen). Dazu je Treffer 1,0 über
    ``TEXT_V2_HORIZON_BINS`` ab dem Wort: Marker aus ``cfg["markers"]`` (Überraschung, Negation einer
    Erwartung, Stakes, Zitat; ``reaction`` nur in kurzen Einwürfen) und Zahlen mit Einheit (Ziffer oder Zahlwort,
    gefolgt von einer Einheit aus ``cfg["units"]`` oder mit angehängtem Prozent- oder Eurozeichen). Reaktionen: ein
    Redebeitrag von höchstens ``REACTION_MAX_WORDS`` Wörtern zwischen Beiträgen eines anderen Sprechers (Einwurf,
    Nachfrage) markiert die ``REACTION_LOOKBACK_BINS`` davor. Lachen zählt nur, wenn ``laughter`` Werte je Bin
    hat (heute nicht berechnet, dann bleibt es außen vor)."""
    h = text_heatmap(list(words), n_bins, bin_s)
    stats = {k: 0 for k in (*HEAT_MARKER_KEYS, "number_unit", "short_turn", "laughter")}
    if not words:
        return h, stats

    def bin_of(t: float) -> int:
        return min(max(int(t / bin_s), 0), len(h) - 1)

    cores = [_core(w.get("text", "")) for w in words]
    turns = _turns(words)
    short_turn_of: dict[int, bool] = {}
    for n, (a, b) in enumerate(turns):
        short = (
            b - a + 1 <= REACTION_MAX_WORDS
            and 0 < n < len(turns) - 1
            and words[turns[n - 1][0]].get("speaker") == words[turns[n + 1][0]].get("speaker")
            and words[a].get("speaker") is not None
        )
        for i in range(a, b + 1):
            short_turn_of[i] = short
        if short:
            stats["short_turn"] += 1
            b0 = bin_of(float(words[a]["start"]))
            h[max(0, b0 - REACTION_LOOKBACK_BINS) : b0 + 1] += 1.0
    for key in HEAT_MARKER_KEYS:
        for phrase in cfg["markers"][key]:
            for k in _phrase_hits(cores, phrase):
                if key == "reaction" and not short_turn_of.get(k, False):
                    continue
                stats[key] += 1
                b0 = bin_of(float(words[k]["start"]))
                if key == "reaction":
                    h[max(0, b0 - REACTION_LOOKBACK_BINS) : b0 + 1] += 1.0
                else:
                    h[b0 : b0 + TEXT_V2_HORIZON_BINS] += 1.0
    units = set(cfg["units"])
    for i, w in enumerate(words):
        raw = str(w.get("text", ""))
        numeric = bool(re.search(r"\d", raw)) or cores[i] in NUMBER_WORDS
        if not numeric:
            continue
        attached = raw.rstrip(_PUNCT.replace("%", "").replace("€", "")).endswith(("%", "€"))
        if attached or (i + 1 < len(words) and cores[i + 1] in units):
            stats["number_unit"] += 1
            b0 = bin_of(float(w["start"]))
            h[b0 : b0 + TEXT_V2_HORIZON_BINS] += 1.0
    if laughter is not None and len(laughter) == len(h) and any(float(x) > 0 for x in laughter):
        lv = np.asarray(laughter, dtype=np.float32)
        stats["laughter"] = int((lv > 0).sum())
        h = h + lv
    return h, stats


def zscore(v: np.ndarray) -> np.ndarray:
    """z-Wert wie im Audioanteil (Median, Standardabweichung), begrenzt auf -3 bis 3; flach heißt null."""
    std = float(np.std(v)) if len(v) else 0.0
    if std < 1e-9:
        return np.zeros(len(v), dtype=np.float32)
    return np.clip((v - np.median(v)) / std, -3, 3).astype(np.float32)


def combined_v2(
    audio: np.ndarray | None,
    words: Sequence[Mapping[str, Any]],
    cfg: Mapping[str, Any],
    bin_s: float = 1.0,
    laughter: Sequence[float] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Audio und Text v2, beide z-normiert, gemischt mit ``cfg["text_weight"]``: ``(1 - w) * audio + w * text``.

    Ohne Audio (``None`` oder leer) zählt nur der Text, die Bins reichen bis zum letzten Wort. Rückgabe:
    Heatmap, z-normierter Textanteil, Trefferzahl je Merkmal."""
    if audio is None or len(audio) == 0:
        end = max((float(w["end"]) for w in words), default=0.0)
        a = np.zeros(max(1, math.ceil(end / bin_s)), dtype=np.float32)
    else:
        a = np.asarray(audio, dtype=np.float32)
    raw, stats = text_heatmap_v2(words, len(a), cfg, bin_s, laughter)
    t = zscore(raw)
    w = float(cfg["text_weight"])
    return ((1.0 - w) * a + w * t).astype(np.float32), t, stats


def payload_with_text_v2(heat: Mapping[str, Any] | None, words: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> dict:
    """Heatmap-Nutzlast mit Text v2 neu gemischt: ``values`` und ``seeds`` neu, ``text_values`` (z-normierter
    Textanteil) und ``text_v2`` (Gewicht, Treffer je Merkmal, ob Audio und Lachen vorlagen) dazu. Der
    Audioanteil kommt aus ``audio_values``; fehlt er, zählt nur der Text (``audio_missing``). Alle übrigen
    Schlüssel bleiben, die gespeicherte Heatmap wird nicht verändert."""
    src = dict(heat or {})
    bin_s = float(src.get("bin_s") or 1.0) or 1.0
    audio = src.get("audio_values")
    a = np.asarray(audio, dtype=np.float32) if audio else None
    laughter = src.get("laughter_values") or None
    values, text, stats = combined_v2(a, words, cfg, bin_s, laughter)
    top_k = max(len(src.get("seeds") or []), 25)
    gap = max(1, int(round(45 / bin_s)))
    out = {**src, "bin_s": bin_s, "n_bins": int(len(values))}
    out["values"] = [round(float(v), 4) for v in values]
    out["seeds"] = [round(int(b) * bin_s, 3) if bin_s != 1.0 else int(b) for b in seeds(values, top_k=top_k, min_gap_s=gap)]
    out["text_values"] = [round(float(v), 4) for v in text]
    out["text_v2"] = {
        "text_weight": float(cfg["text_weight"]), "hits": stats, "audio_missing": a is None,
        "laughter_used": stats["laughter"] > 0, "method": "text_v2_zscore",
    }  # fmt: skip
    return out


__all__ = [
    "DISCOURSE_MARKERS",
    "HEAT_MARKER_KEYS",
    "HEAT_SWITCH",
    "audio_heatmap",
    "combined",
    "combined_v2",
    "payload_with_text_v2",
    "read_wav_mono",
    "seeds",
    "text_heat_settings",
    "text_heatmap",
    "text_heatmap_v2",
    "to_payload",
    "zscore",
]
