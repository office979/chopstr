"""Schnittkanten an Wortgrenzen, Sicherheit der Kanten und Prüfung der Klebestellen (AP10b).

Gilt nur unter Fassung 2 mit dem Schalter ``implementation.cut.padding`` und der Regel ``cut.padding``
(``editorial.cut_settings``). Ohne beides gibt ``cut_rules`` ``None`` zurück und der Render schneidet wie
bisher exakt auf den Segmentzeiten (Rollback).

Kanonische Zeitbasis sind Sekunden auf der Audioebene der Quelle. Es gibt keine Rasterung auf Frames;
Quellen mit variabler Bildrate werden im Render-Plan nur gekennzeichnet (``render_plan.timebase``), das
Verhalten dort ist nicht geprüft.

``pad_segments`` setzt Vor- und Nachlauf an Wortgrenzen:

* Start höchstens ``cut.lead_in_s`` vor dem ersten Wort des Segments, nie vor dem Ende des vorigen Wortes.
* Ende höchstens ``cut.lead_out_s`` nach dem letzten Wort, nie in das nächste Wort.
* Liegen die Wörter lückenlos (Ende des einen gleich Anfang des nächsten), gibt es kein Padding.
* Eine Kante, die schon in der Stille liegt und weiter vom Wort entfernt ist (bewusst gelassene Pause aus
  der Kürzung oder dem Editor), bleibt stehen; gekürzt wird eine Kante nur, wenn sie in einem Wort liegt.
  Ein Wort, dessen Mitte außerhalb des Segments liegt, fällt damit ganz heraus statt halb hörbar zu sein.
* Bei niedriger Sicherheit (``boundary_confidence`` unter ``cut.low_confidence_threshold``) liegt die
  Kante konservativ in der Stille: höchstens bis zur Mitte der Lücke zum Nachbarwort, nie ins Wort, und
  das Segment trägt ``low_confidence``.
* An einer Naht, an der das nächste Segment in der Quelle direkt mit dem Folgewort weitergeht (nur eine
  Pause wurde entfernt), teilen sich beide Seiten die Lücke an ihrer Mitte; würden sie sich trotzdem
  berühren, bleibt die Naht ungepaddet (sonst wäre der Ton doppelt oder die Kürzung verschwunden).

``boundary_confidence(words, idx, side)`` (0 bis 1, origin H, nicht gemessen) für die Kante vor
(``start``) oder nach (``end``) Wort ``idx``; betrachtet werden das Wort und sein Nachbar an dieser Kante::

    p      = min(prob des Wortes, prob des Nachbarn)        (prob fehlt: 0,5; Fixtures: asr_confidence)
    g      = min(1, Lücke zum Nachbarn / FULL_GAP_S)        (kein Nachbar: 1; Überlappung: 0)
    t      = 0,5, wenn die Wortzeit zweifelhaft ist, sonst 1
             zweifelhaft: Dauer null oder negativ bei einem der beiden Wörter, Überlappung der beiden,
             oder Wortzeitquelle ``time_source`` geschätzt (estimated, interpolated, manual)
    conf   = round(t * (0,6 * p + 0,4 * g), 3)

``FULL_GAP_S`` = 0,25 s: ab dieser Stille gilt eine Kante als frei (RK 7, Zeile Pausen: Median der
Wortlücke 288 ms, DSCVRY n = 62). Die Gewichte 0,6 und 0,4 sind gesetzt, nicht gemessen (origin H). Heute
schreibt kein Transkript ``time_source``; alle Wortzeiten kommen aus den ASR-Wortzeitstempeln.

``check_transitions(plan, words)`` prüft jede Kante und jede Klebestelle des Plans: Schnitt innerhalb eines
Wortes (hoch; mittel nur, wenn die Kante auf einer Wortgrenze liegt und sich die Wortzeiten dort
überlappen), Restpause an der Naht unter ``cut.min_gap_s`` (mittel), Sprecherwechsel an der Naht ohne Grund
(mittel; Grund ist ein Teaser oder eine Naht, an der die Quelle direkt weiterläuft), Wort halb im Segment,
das keine Caption bekommt (mittel). Die Schwere ist ``high`` oder ``medium`` wie bei ``fidelity.check_cut``;
``high`` sperrt über ``inhalt_fehler`` (P16) das Veröffentlichen.

Prosodische Schnittkanten (Lane P4, Schalter ``implementation.cut.prosody``, Regel ``cut.prosody.enabled``,
Standard aus; wirksam nur zusammen mit ``cut.padding``): ``prosody_edges`` legt jede Kante eines gepaddeten
Segments auf das Pegelminimum (RMS, Fenster ``FRAME_S`` 20 ms, Schritt ``HOP_S`` 10 ms) des 16-kHz-Audios
im Suchfenster ``cut.prosody.search_window_s`` vor dem ersten beziehungsweise nach dem letzten Wort. Das
Fenster endet immer in der Stille: nie im Nachbarwort, nie im eigenen Wort (Abstand ``GUARD_S``), an einer
Naht oder bei niedriger Sicherheit nur bis zur Mitte der Lücke (wie ``pad_segments``), nie in einer
geschützten Spanne (``protected``, Zeitbereiche aus ``trim_plan.protected_spans``). Unter den Fenstern,
deren Pegel höchstens ``NEAR_MIN_FACTOR`` mal dem Minimum entspricht, gewinnt das, das der gepaddeten
Kante am nächsten liegt; in gleichmäßiger Stille bleibt die Kante also, wo das Padding sie hingelegt hat.
Atem: ein Lauf aus Fenstern mit Pegel über der Stille (``BREATH_FLOOR_FACTOR`` mal Grundrauschen) und unter
der Sprache (``BREATH_SPEECH_RATIO`` mal Sprachpegel), mit Hochfrequenzanteil (Energie über
``HF_SPLIT_HZ``) ab ``BREATH_HF_MIN``, ``BREATH_MIN_S`` bis ``BREATH_MAX_S`` lang und höchstens
``BREATH_ADJ_S`` vor dem Wortbeginn, gilt als Atem; der Schnitt liegt davor. Die 20-ms-Blenden des Renders
bleiben. Alle Konstanten sind gesetzt, nicht gemessen (origin H). Ergebnis je Kante::

    edge = {chosen_s, text_s, rms_min_s, breath, confidence}

``chosen_s`` ist die Schnittzeit, ``text_s`` die Wortgrenze, ``rms_min_s`` das Fenster mit dem kleinsten
Pegel (``None`` ohne Audio oder ohne Raum), ``confidence`` gleich 1 minus Pegel an der Kante durch
Sprachpegel (0 bis 1, ``None`` ohne Audio). Ob die Schnitte natürlich klingen, misst das nicht; dafür
braucht es einen Hörtest (docs/decisions/040-prosodische-schnittgrenzen.md).

Hook gegen den Ton (Lane P4, Schalter ``implementation.cut.hook_audio``, Regel ``cut.hook_audio.enabled``,
Standard aus; wirksam nur zusammen mit ``cut.padding``): ``shift_preamble`` verschiebt den Einstieg hinter
Vorgeplänkel (ganze Sätze nur aus Füllwörtern, Rückmeldesignalen, Begrüßungen und Einleitungsfloskeln der
Policy), wenn die Satzgrenzen (``dach_nlp.sentence_end_kinds``, Ende ``punct`` oder ``speaker_change``) es
erlauben und keine geschützte Spanne berührt wird; ``hook_audio_report`` prüft, dass Sprache innerhalb
``cut.hook_audio.max_lead_s`` beginnt (Pegel über ``SPEECH_ONSET_RATIO`` mal Sprachpegel) und der Hook-Satz
innerhalb ``cut.hook_audio.hook_window_s``::

    hook_audio = {speech_onset_s, hook_onset_s, preamble_removed_s, ok, basis}
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .. import editorial

FULL_GAP_S = 0.25
PROB_WEIGHT = 0.6
GAP_WEIGHT = 0.4
UNKNOWN_PROB = 0.5
DOUBTFUL_TIMING_FACTOR = 0.5
ESTIMATED_TIME_SOURCES = frozenset({"estimated", "interpolated", "manual"})
# Toleranz für Zeitvergleiche; Plan und Wörter sind auf Millisekunden gerundet.
EDGE_EPS_S = 0.005


@dataclass(frozen=True)
class CutRules:
    lead_in_s: float
    lead_out_s: float
    min_gap_s: float
    low_confidence_threshold: float


def cut_rules(policy: editorial.Policy | None = None) -> CutRules | None:
    """Regeln aus ``cut`` der übergebenen oder aktiven Fassung; ``None`` heißt: kein Padding (v1, Schalter aus)."""
    settings = editorial.cut_settings(policy if policy is not None else editorial.load())
    return None if settings is None else CutRules(**settings)


def _rules(policy: editorial.Policy | CutRules | None) -> CutRules | None:
    return policy if isinstance(policy, CutRules) else cut_rules(policy)


def _prob(w: dict) -> float:
    raw = w.get("prob")
    if raw is None:
        raw = w.get("asr_confidence")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return min(1.0, max(0.0, float(raw)))
    return UNKNOWN_PROB


def _doubtful(w: dict) -> bool:
    return float(w["end"]) - float(w["start"]) <= 0 or str(w.get("time_source") or "").lower() in ESTIMATED_TIME_SOURCES


def boundary_confidence(words: list[dict], idx: int, side: str = "end") -> float:
    """Sicherheit der Kante vor (``side="start"``) oder nach (``side="end"``) Wort ``idx``, Formel im Modulkopf."""
    if side not in ("start", "end"):
        raise ValueError(f"side muss start oder end sein, nicht {side!r}")
    w = words[idx]
    j = idx - 1 if side == "start" else idx + 1
    neighbor = words[j] if 0 <= j < len(words) else None
    p = _prob(w)
    doubtful = _doubtful(w)
    g = 1.0
    if neighbor is not None:
        p = min(p, _prob(neighbor))
        gap = float(w["start"]) - float(neighbor["end"]) if side == "start" else float(neighbor["start"]) - float(w["end"])
        g = min(1.0, max(0.0, gap / FULL_GAP_S))
        doubtful = doubtful or _doubtful(neighbor) or gap < 0
    t = DOUBTFUL_TIMING_FACTOR if doubtful else 1.0
    return round(t * (PROB_WEIGHT * p + GAP_WEIGHT * g), 3)


def segment_confidence(words: list[dict], first: int, last: int) -> float:
    """Sicherheit eines Segments mit den Wörtern ``first`` bis ``last``: die schwächere seiner beiden Kanten."""
    return min(boundary_confidence(words, first, "start"), boundary_confidence(words, last, "end"))


def _mid(w: dict) -> float:
    return (float(w["start"]) + float(w["end"])) / 2.0


def edge_words(words: list[dict], start: float, end: float) -> tuple[int, int] | None:
    """Erstes und letztes Wort, dessen Mitte im Segment liegt (halboffen wie ``compose.remap_words`` mit
    ``by_midpoint``); ``None`` ohne Wort."""
    ids = [i for i, w in enumerate(words) if start <= _mid(w) < end]
    return (ids[0], ids[-1]) if ids else None


def clamp_to_neighbors(words: list[dict], first: int, last: int, start: float, end: float) -> tuple[float, float]:
    """Kanten ``start`` und ``end`` eines Bereichs mit den Wörtern ``first`` bis ``last``: nie vor das Ende des
    Vorworts, nie in das Folgewort; die eigenen Wörter bleiben immer ganz drin (bei überlappenden Wortzeiten
    gewinnt das eigene Wort). Für ``compose.from_keep_ranges`` unter ``cut.padding``."""
    if first > 0:
        start = max(start, min(float(words[first - 1]["end"]), float(words[first]["start"])))
    if last + 1 < len(words):
        end = min(end, max(float(words[last + 1]["start"]), float(words[last]["end"])))
    return start, end


def pad_segments(segments: list[dict], words: list[dict], policy: editorial.Policy | CutRules | None = None) -> list[dict]:
    """Segmente in Abspielreihenfolge mit Vor- und Nachlauf an Wortgrenzen (Regeln im Modulkopf).

    Rückgabe je Segment: ``start``, ``end``, ``role``, ``boundary_confidence`` (``None`` ohne Wort),
    ``low_confidence``. Ohne aktive Regeln (Fassung 1, Schalter aus) oder ohne Wörter bleiben die Zeiten
    unverändert und die Sicherheit ist ``None``."""
    rules = _rules(policy)
    base = [{"start": float(s["start"]), "end": float(s["end"]), "role": str(s.get("role") or "body")} for s in segments]
    if rules is None or not words:
        return [{**s, "boundary_confidence": None, "low_confidence": False} for s in base]
    n = len(words)
    edges = [edge_words(words, s["start"], s["end"]) for s in base]
    # Naht k-1 -> k, an der die Quelle direkt mit dem Folgewort weiterläuft (nur eine Pause entfernt).
    continuous = [
        k > 0 and edges[k] is not None and edges[k - 1] is not None and edges[k - 1][1] + 1 == edges[k][0]
        for k in range(len(base))
    ]  # fmt: skip
    out: list[dict] = []
    for k, (seg, e) in enumerate(zip(base, edges)):
        if e is None:
            out.append({**seg, "boundary_confidence": None, "low_confidence": False})
            continue
        f, last = e
        conf_in = boundary_confidence(words, f, "start")
        conf_out = boundary_confidence(words, last, "end")
        low_in = conf_in < rules.low_confidence_threshold
        low_out = conf_out < rules.low_confidence_threshold
        seam_in = continuous[k]
        seam_out = k + 1 < len(base) and continuous[k + 1]

        w_f = words[f]
        if f > 0:
            prev_end = float(words[f - 1]["end"])
            room = float(w_f["start"]) - prev_end
            half = low_in or seam_in
            amount = min(rules.lead_in_s, room / 2.0 if half else room)
            floor = prev_end + room / 2.0 if half and room > 0 else prev_end
        else:
            amount = min(rules.lead_in_s, float(w_f["start"]))
            floor = 0.0
        target = float(w_f["start"]) - max(amount, 0.0)
        start = seg["start"] if floor <= seg["start"] <= target else target

        w_l = words[last]
        if last + 1 < n:
            next_start = float(words[last + 1]["start"])
            room = next_start - float(w_l["end"])
            half = low_out or seam_out
            amount = min(rules.lead_out_s, room / 2.0 if half else room)
            ceil = float(w_l["end"]) + room / 2.0 if half and room > 0 else next_start
        else:
            amount = rules.lead_out_s
            ceil = float("inf")
        target = float(w_l["end"]) + max(amount, 0.0)
        end = seg["end"] if target <= seg["end"] <= ceil else target

        conf = min(conf_in, conf_out)
        out.append({
            "start": round(max(start, 0.0), 3), "end": round(end, 3), "role": seg["role"],
            "boundary_confidence": conf, "low_confidence": conf < rules.low_confidence_threshold,
        })  # fmt: skip
    # Eine Naht, an der beide Seiten sich nach dem Padding berühren oder überlappen, bleibt wie vorher.
    for k in range(1, len(out)):
        if continuous[k] and out[k - 1]["end"] >= out[k]["start"]:
            out[k - 1]["end"] = round(base[k - 1]["end"], 3)
            out[k]["start"] = round(base[k]["start"], 3)
    for s in out:
        if s["end"] <= s["start"]:
            raise ValueError(f"Segment nach dem Padding ohne Länge ({s['start']:.3f} bis {s['end']:.3f})")
    return out


def _finding(kind: str, severity: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"type": f"transition_{kind}", "severity": severity, "detail": detail, **extra}


def check_transitions(plan: dict, words: list[dict], policy: editorial.Policy | CutRules | None = None) -> list[dict]:
    """Befunde je Kante und Klebestelle des Plans (``plan["segments"]`` in Abspielreihenfolge), siehe Modulkopf.

    ``cut.min_gap_s`` kommt aus den Regeln der übergebenen oder aktiven Fassung; ohne aktive Regeln entfällt
    nur die Prüfung der Restpause."""
    rules = _rules(policy)
    segs = [(float(s["start"]), float(s["end"]), str(s.get("role") or "body")) for s in plan.get("segments") or []]
    if not segs or not words:
        return []
    boundaries = {round(float(w[key]), 3) for w in words for key in ("start", "end")}
    findings: list[dict] = []
    for k, (s0, s1, _role) in enumerate(segs):
        for edge, t in (("in", s0), ("out", s1)):
            for i, w in enumerate(words):
                ws, we = float(w["start"]), float(w["end"])
                if ws + EDGE_EPS_S < t < we - EDGE_EPS_S:
                    on_boundary = any(abs(t - b) <= EDGE_EPS_S for b in boundaries)
                    findings.append(_finding(
                        "cut_in_word", "medium" if on_boundary else "high",
                        f"Schnitt bei {t:.2f} s liegt im Wort „{w.get('text')}“"
                        + (" (Wortzeiten überlappen, Grenze unsicher)" if on_boundary else ""),
                        segment_index=k, edge=edge, time_s=round(t, 3), word_index=i,
                    ))  # fmt: skip
        for i, w in enumerate(words):
            ws, we = float(w["start"]), float(w["end"])
            if ws < s1 and we > s0 and not (s0 <= ws and we <= s1) and not (s0 <= _mid(w) < s1):
                findings.append(_finding(
                    "caption_lost", "medium",
                    f"Wort „{w.get('text')}“ ist zum Teil hörbar, bekommt aber keine Untertitel",
                    segment_index=k, word_index=i,
                ))  # fmt: skip
    edges = [edge_words(words, s0, s1) for s0, s1, _ in segs]
    for k in range(1, len(segs)):
        a, b = edges[k - 1], edges[k]
        if a is None or b is None:
            continue
        last, first = a[1], b[0]
        (_a0, a1, role_a), (b0, _b1, role_b) = segs[k - 1], segs[k]
        if rules is not None:
            rest = max(0.0, a1 - float(words[last]["end"])) + max(0.0, float(words[first]["start"]) - b0)
            if rest < rules.min_gap_s:
                findings.append(_finding(
                    "gap_short", "medium",
                    f"An der Klebestelle bleiben {rest:.2f} s Pause, weniger als {rules.min_gap_s:.2f} s; die Wörter stoßen aneinander",
                    segment_index=k, rest_s=round(rest, 3),
                ))  # fmt: skip
        spk_a, spk_b = words[last].get("speaker"), words[first].get("speaker")
        reason = "teaser" in (role_a, role_b) or first == last + 1
        if spk_a is not None and spk_b is not None and spk_a != spk_b and not reason:
            findings.append(_finding(
                "speaker_change", "medium",
                f"An der Klebestelle wechselt der Sprecher ({spk_a} zu {spk_b}), obwohl dazwischen geschnitten wurde",
                segment_index=k,
            ))  # fmt: skip
    return findings


# -- Lane P4: prosodische Schnittkanten ------------------------------------------------------------
PROSODY_SWITCH = "cut.prosody"
HOOK_AUDIO_SWITCH = "cut.hook_audio"
FRAME_S = 0.02
HOP_S = 0.01
# Abstand der Kante zur Wortgrenze, damit der Einsatz oder das Ausklingen eines Wortes nie im Fenster liegt.
GUARD_S = 0.01
# Fenster bis zu diesem Vielfachen des Minimums gelten als gleich leise (Rauschen in der Stille).
NEAR_MIN_FACTOR = 1.5
NEAR_MIN_ABS = 1e-4
# Unter diesem Pegel ist ein Fenster Stille (etwa -80 dBFS); dort gibt es keinen Hochfrequenzanteil.
SILENCE_RMS = 1e-4
HF_SPLIT_HZ = 2000.0
BREATH_HF_MIN = 0.35
BREATH_FLOOR_FACTOR = 3.0
BREATH_SPEECH_RATIO = 0.5
BREATH_MIN_S = 0.08
BREATH_MAX_S = 0.6
BREATH_ADJ_S = 0.08
# Sprachpegel: Median der Fenster im angrenzenden Wort, höchstens so viel Wort wird gelesen.
SPEECH_REF_MAX_S = 0.5
SPEECH_ONSET_RATIO = 0.25


class Audio(Protocol):
    """Mono-Audio, fensterweise lesbar: ``sr`` Abtastrate, ``read(t0, t1)`` Werte von -1 bis 1."""

    sr: int

    def read(self, t0: float, t1: float) -> np.ndarray: ...


class PcmAudio:
    """Mono-PCM im Speicher (Tests und kurze Quellen)."""

    def __init__(self, sr: int, samples: np.ndarray):
        self.sr = int(sr)
        self.samples = np.asarray(samples, dtype=np.float32)

    def read(self, t0: float, t1: float) -> np.ndarray:
        a, b = max(0, int(round(t0 * self.sr))), max(0, int(round(t1 * self.sr)))
        return self.samples[a:b]


class WavAudio:
    """16-kHz-WAV der Ingest-Stufe (16 bit PCM), fensterweise über ``wave`` gelesen, nie ganz im Speicher.
    Dieselbe Umrechnung wie ``signals.read_wav_mono``."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with wave.open(self.path, "rb") as wf:
            self.sr = wf.getframerate()
            self.channels = wf.getnchannels()
            self.width = wf.getsampwidth()
            self.frames = wf.getnframes()
        if self.width != 2:
            raise ValueError(f"WAV mit {8 * self.width} bit, erwartet 16 bit PCM")

    def read(self, t0: float, t1: float) -> np.ndarray:
        a = min(self.frames, max(0, int(round(t0 * self.sr))))
        b = min(self.frames, max(a, int(round(t1 * self.sr))))
        with wave.open(self.path, "rb") as wf:
            wf.setpos(a)
            raw = np.frombuffer(wf.readframes(b - a), dtype=np.int16).astype(np.float32) / 32768.0
        if self.channels > 1:
            raw = raw.reshape(-1, self.channels).mean(axis=1)
        return raw


@dataclass(frozen=True)
class ProsodyRules:
    search_window_s: float


@dataclass(frozen=True)
class HookAudioRules:
    max_lead_s: float
    hook_window_s: float


def _switch_on(policy: editorial.Policy, path: str) -> bool:
    value: Any = policy.roh.get("implementation") or {}
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return value is True


def _cut_subsection(policy: editorial.Policy, name: str, switch: str) -> dict | None:
    """``cut.<name>`` der Fassung, wenn Fassung 2, ``cut.padding`` gilt, der Schalter an und ``enabled`` true ist."""
    if policy.version < 2 or not _switch_on(policy, switch) or editorial.cut_settings(policy) is None:
        return None
    raw = (policy.roh.get("cut") or {}).get(name)
    label = f"clip_policy_v{policy.version}: cut.{name}"
    if not isinstance(raw, dict) or not isinstance(raw.get("enabled"), bool):
        raise editorial.PolicyError(f"{label}.enabled ist true oder false ({switch} ist an).")
    return raw if raw["enabled"] else None


def _positive(raw: dict, key: str, label: str) -> float:
    try:
        value = float(raw[key])
    except (KeyError, TypeError, ValueError):
        raise editorial.PolicyError(f"{label}.{key} fehlt oder ist keine Zahl.") from None
    if value <= 0:
        raise editorial.PolicyError(f"{label}.{key} muss größer als 0 sein.")
    return value


def prosody_rules(policy: editorial.Policy | None = None) -> ProsodyRules | None:
    """Regeln ``cut.prosody.enabled`` und ``cut.prosody.search_window_s``; ``None`` heißt: Kanten bleiben, wo das
    Padding sie hinlegt (Fassung 1, Schalter ``implementation.cut.prosody`` aus, Regel aus oder ohne ``cut.padding``)."""
    pol = policy if policy is not None else editorial.load()
    raw = _cut_subsection(pol, "prosody", PROSODY_SWITCH)
    if raw is None:
        return None
    return ProsodyRules(search_window_s=_positive(raw, "search_window_s", f"clip_policy_v{pol.version}: cut.prosody"))


def hook_audio_rules(policy: editorial.Policy | None = None) -> HookAudioRules | None:
    """Regeln ``cut.hook_audio.enabled``, ``cut.hook_audio.max_lead_s`` und ``cut.hook_audio.hook_window_s``;
    ``None`` heißt: keine Prüfung und kein Verschieben (Fassung 1, Schalter ``implementation.cut.hook_audio`` aus,
    Regel aus oder ohne ``cut.padding``)."""
    pol = policy if policy is not None else editorial.load()
    raw = _cut_subsection(pol, "hook_audio", HOOK_AUDIO_SWITCH)
    if raw is None:
        return None
    label = f"clip_policy_v{pol.version}: cut.hook_audio"
    return HookAudioRules(max_lead_s=_positive(raw, "max_lead_s", label), hook_window_s=_positive(raw, "hook_window_s", label))


def frame_analysis(audio: Audio, lo: float, hi: float) -> list[tuple[float, float, float]]:
    """Fenster mit Mitte von ``lo`` bis ``hi`` im Abstand ``HOP_S``: ``(t, rms, hf_anteil)``."""
    if hi < lo:
        return []
    n = int(np.floor((hi - lo) / HOP_S + 1e-9)) + 1
    half = FRAME_S / 2.0
    t0 = max(0.0, lo - half)
    buf = audio.read(t0, hi + half)
    sr = audio.sr
    size = max(1, int(round(FRAME_S * sr)))
    window = np.hanning(size).astype(np.float32)
    freqs = np.fft.rfftfreq(size, 1.0 / sr)
    high = freqs >= HF_SPLIT_HZ
    out: list[tuple[float, float, float]] = []
    for k in range(n):
        t = round(lo + k * HOP_S, 4)
        a = int(round((t - half - t0) * sr))
        seg = buf[max(0, a) : max(0, a) + size]
        if len(seg) < size:
            seg = np.pad(seg, (0, size - len(seg)))
        rms = float(np.sqrt(np.mean(seg.astype(np.float64) ** 2)))
        hf = 0.0
        if rms > SILENCE_RMS:
            spec = np.abs(np.fft.rfft(seg * window)) ** 2
            total = float(spec.sum())
            hf = float(spec[high].sum() / total) if total > 0 else 0.0
        out.append((t, rms, hf))
    return out


def speech_level(audio: Audio, word: dict) -> float:
    """Sprachpegel eines Wortes: Median des Pegels seiner Fenster (höchstens ``SPEECH_REF_MAX_S``)."""
    ws = float(word["start"])
    we = min(float(word["end"]), ws + SPEECH_REF_MAX_S)
    frames = frame_analysis(audio, ws + FRAME_S / 2.0, max(ws + FRAME_S / 2.0, we - FRAME_S / 2.0))
    return max(float(np.median([r for _t, r, _h in frames])) if frames else 0.0, SILENCE_RMS)


def find_breath(frames: list[tuple[float, float, float]], onset: float, speech: float, side: str = "before") -> tuple[float, float] | None:
    """Atem unmittelbar vor ``onset`` (Wortbeginn): ``(start, ende)`` des Laufs oder ``None``.

    ``frames`` liegen in der Lücke vor dem Wort. Grundrauschen ist das untere Zehntel der Pegel der Lücke."""
    if side != "before" or not frames:
        return None
    floor = max(float(np.percentile([r for _t, r, _h in frames], 10)), SILENCE_RMS)
    run_end: float | None = None
    run_start: float | None = None
    for t, rms, hf in reversed(frames):
        breath_like = floor * BREATH_FLOOR_FACTOR < rms < speech * BREATH_SPEECH_RATIO and hf >= BREATH_HF_MIN
        if run_end is None:
            if onset - t > BREATH_ADJ_S + FRAME_S:
                return None
            if breath_like:
                run_end = run_start = t
            continue
        if not breath_like:
            break
        run_start = t
    if run_end is None or run_start is None:
        return None
    start, end = run_start - FRAME_S / 2.0, run_end + FRAME_S / 2.0
    return (round(start, 3), round(end, 3)) if BREATH_MIN_S <= end - start <= BREATH_MAX_S else None


def _outside(t: float, protected: list[tuple[float, float]]) -> bool:
    return not any(a - FRAME_S / 2.0 < t < b + FRAME_S / 2.0 for a, b in protected)


def _choose_edge(
    audio: Audio | None,
    text_s: float,
    target: float,
    lo: float,
    hi: float,
    speech: float,
    breath_onset: float | None,
    protected: list[tuple[float, float]],
) -> dict[str, Any]:
    """Eine Kante: Pegelminimum in ``[lo, hi]``, bei Atem vor ``breath_onset`` nur vor dem Atem."""
    edge: dict[str, Any] = {"chosen_s": round(target, 3), "text_s": round(text_s, 3), "rms_min_s": None, "breath": False, "confidence": None}
    if audio is None or hi - lo < HOP_S:
        return edge
    frames = frame_analysis(audio, lo, hi)
    if breath_onset is not None:
        gap_frames = frame_analysis(audio, lo, breath_onset - FRAME_S / 2.0) if breath_onset - FRAME_S / 2.0 >= lo else []
        breath = find_breath(gap_frames, breath_onset, speech)
        if breath is not None:
            edge["breath"] = True
            frames = [f for f in frames if f[0] + FRAME_S / 2.0 <= breath[0] + 1e-9]
            if not frames:
                edge["chosen_s"] = round(lo, 3)
                return edge
            target = min(target, breath[0])
    frames = [f for f in frames if _outside(f[0], protected)]
    if not frames:
        return edge
    t_min, r_min, _ = min(frames, key=lambda f: (f[1], abs(f[0] - target)))
    near = [f for f in frames if f[1] <= r_min * NEAR_MIN_FACTOR + NEAR_MIN_ABS]
    t_chosen, r_chosen, _ = min(near, key=lambda f: (abs(f[0] - target), f[0]))
    edge.update(
        chosen_s=round(t_chosen, 3),
        rms_min_s=round(t_min, 3),
        confidence=round(min(1.0, max(0.0, 1.0 - r_chosen / speech)), 3),
    )
    return edge


def prosody_edges(
    padded: list[dict],
    words: list[dict],
    audio: Audio | None,
    rules: ProsodyRules,
    protected: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Gepaddete Segmente (``pad_segments``) mit Kanten auf dem Pegelminimum (Modulkopf).

    Rückgabe: dieselben Segmente mit neuem ``start``, ``end`` und ``edges = {"in": edge, "out": edge}``;
    Segmente ohne Wort bleiben ohne ``edges``. Ohne Audio bleiben die Zeiten, die Kanten tragen ``rms_min_s``
    und ``confidence`` ``None``."""
    prot = [(float(a), float(b)) for a, b in (protected or [])]
    edges = [edge_words(words, float(s["start"]), float(s["end"])) for s in padded]
    continuous = [
        k > 0 and edges[k] is not None and edges[k - 1] is not None and edges[k - 1][1] + 1 == edges[k][0]
        for k in range(len(padded))
    ]  # fmt: skip
    out: list[dict] = []
    for k, (seg, e) in enumerate(zip(padded, edges)):
        if e is None:
            out.append(dict(seg))
            continue
        f, last = e
        low = bool(seg.get("low_confidence"))
        w_f, w_l = words[f], words[last]
        own_in = speech_level(audio, w_f) if audio is not None else SILENCE_RMS
        own_out = speech_level(audio, w_l) if audio is not None else SILENCE_RMS

        text_in = float(w_f["start"])
        prev_end = float(words[f - 1]["end"]) if f > 0 else 0.0
        floor = prev_end + (text_in - prev_end) / 2.0 if (low or continuous[k]) and f > 0 else prev_end
        lo_in = max(floor, text_in - rules.search_window_s, 0.0)
        e_in = _choose_edge(audio, text_in, float(seg["start"]), lo_in, text_in - GUARD_S, own_in, text_in, prot)

        text_out = float(w_l["end"])
        seam_out = k + 1 < len(padded) and continuous[k + 1]
        if last + 1 < len(words):
            next_start = float(words[last + 1]["start"])
            ceil = text_out + (next_start - text_out) / 2.0 if low or seam_out else next_start
            onset = next_start
        else:
            ceil, onset = float("inf"), None
        hi_out = min(ceil, text_out + rules.search_window_s)
        if onset is not None and hi_out >= onset - GUARD_S:
            hi_out = onset - GUARD_S
        e_out = _choose_edge(audio, text_out, float(seg["end"]), text_out + GUARD_S, hi_out, own_out, onset, prot)

        start, end = float(e_in["chosen_s"]), float(e_out["chosen_s"])
        if end <= start:
            raise ValueError(f"Segment nach den prosodischen Kanten ohne Länge ({start:.3f} bis {end:.3f})")
        out.append({**seg, "start": round(start, 3), "end": round(end, 3), "edges": {"in": e_in, "out": e_out}})
    return out


# -- Lane P4: Hook gegen die ersten Sekunden Ton ---------------------------------------------------
# Wörter, aus denen Vorgeplänkel bestehen darf, zusätzlich zu dach_nlp.HARD_FILLERS und BACKCHANNEL und
# den Wendungen der Policy (trim.removal.edge_markers, einstieg.einleitungsfloskeln). Gesetzt nach dem
# Auftrag (Master-Prompt Phase 4: „also", „ja gut", Begrüßung), nicht gemessen (origin H).
PREAMBLE_WORDS = frozenset({"also", "gut", "so", "na", "nun", "hallo", "hi", "hey", "servus", "moin", "okay", "ok"})
# Höchstens so viel Vorgeplänkel wird entfernt, und nur ganze Sätze.
PREAMBLE_MAX_S = 6.0
PREAMBLE_MAX_SENTENCES = 2
STRONG_SENTENCE_ENDS = frozenset({"punct", "speaker_change"})
_PUNCT = ".,!?;:\"'»«“”„‘’()[]-\u2013"


def _norm(text: str) -> str:
    return " ".join(str(text).lower().replace("ß", "ss").translate(str.maketrans(dict.fromkeys(_PUNCT, " "))).split())


def preamble_phrases(policy: editorial.Policy | None = None) -> list[str]:
    """Wendungen aus ``trim.removal.edge_markers`` und ``einstieg.einleitungsfloskeln`` der Fassung, normalisiert."""
    pol = policy if policy is not None else editorial.load()
    trim = (pol.roh.get("trim") or {}).get("removal") or {}
    einstieg = pol.roh.get("einstieg") or {}
    raw = [*list(trim.get("edge_markers") or []), *list(einstieg.get("einleitungsfloskeln") or [])]
    return sorted({_norm(p) for p in raw if _norm(p)}, key=lambda p: (-len(p), p))


def is_preamble(text: str, phrases: list[str]) -> bool:
    """Ein Satz ist Vorgeplänkel, wenn nach dem Entfernen der Wendungen nur Füllwörter, Rückmeldesignale und
    ``PREAMBLE_WORDS`` übrig bleiben."""
    from . import dach_nlp

    rest = f" {_norm(text)} "
    if not rest.strip():
        return False
    for p in phrases:
        rest = rest.replace(f" {p} ", " ")
    allowed = PREAMBLE_WORDS | set(dach_nlp.HARD_FILLERS) | set(dach_nlp.BACKCHANNEL)
    return all(tok in allowed for tok in rest.split())


def shift_preamble(
    segments: list[dict],
    words: list[dict],
    policy: editorial.Policy | None = None,
    origin_start: float | None = None,
    protected_words: list[tuple[int, int]] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Einstieg hinter Vorgeplänkel verschieben (nur das erste Segment, nur Rolle ``body``, nur ganze Sätze).

    ``origin_start`` ist der Beginn des Kandidaten in Quellzeit: steht vor dem ersten Segment schon
    entferntes Vorgeplänkel (nach einem früheren Render mit Rückschreiben), zählt es mit, damit ein zweiter
    Render denselben Befund ergibt. ``protected_words`` sind Wortbereiche (``trim_plan.protected_spans``),
    die nie entfernt werden. Rückgabe: Segmente und ``{"preamble_removed_s", "hook_word"}``."""
    from . import dach_nlp

    pol = policy if policy is not None else editorial.load()
    info: dict[str, Any] = {"preamble_removed_s": 0.0, "hook_word": None}
    segs = [dict(s) for s in segments]
    if not segs or not words or str(segs[0].get("role") or "body") != "body":
        return segs, info
    first = edge_words(words, float(segs[0]["start"]), float(segs[0]["end"]))
    if first is None:
        return segs, info
    f, last = first
    phrases = preamble_phrases(pol)
    # Satzenden nur im Umfeld des Einstiegs (bis ein Wort hinter das erste Segment, damit dessen letztes
    # Wort seinen Nachfolger sieht); die Regel ist dieselbe wie in der Zerlegung.
    start_t = min(float(segs[0]["start"]), origin_start if origin_start is not None else float(segs[0]["start"]))
    lo_i = next((i for i, w in enumerate(words) if _mid(w) >= start_t - PREAMBLE_MAX_S), f)
    hi_i = min(len(words), last + 2)
    sub = dach_nlp.sentence_end_kinds(words[lo_i:hi_i], rule=editorial.sentence_rule(pol))
    kinds = {lo_i + j: k for j, k in enumerate(sub)}
    prot = [(int(a), int(b)) for a, b in (protected_words or [])]

    def sentences_from(i: int, stop: int) -> list[tuple[int, int]]:
        out, a = [], i
        for j in range(i, stop + 1):
            if kinds[j] != "none":
                out.append((a, j))
                a = j + 1
        return out

    removed_from = f
    if origin_start is not None and origin_start < float(segs[0]["start"]):
        before = [i for i in range(lo_i, f) if _mid(words[i]) >= origin_start]
        if before and before[-1] == f - 1:
            sents = sentences_from(before[0], f - 1)
            covered = sents and sents[-1][1] == f - 1 and sum(b - a + 1 for a, b in sents) == len(before)
            if covered and all(kinds[b] in STRONG_SENTENCE_ENDS and is_preamble(" ".join(str(words[x]["text"]) for x in range(a, b + 1)), phrases) for a, b in sents):
                removed_from = before[0]
    hook = f
    n_new = 0
    for a, b in sentences_from(f, last):
        if n_new >= PREAMBLE_MAX_SENTENCES or b >= last or kinds[b] not in STRONG_SENTENCE_ENDS:
            break
        if not is_preamble(" ".join(str(words[x]["text"]) for x in range(a, b + 1)), phrases):
            break
        if any(pa <= b and a <= pb for pa, pb in prot):
            break
        if float(words[b + 1]["start"]) - float(words[removed_from]["start"]) > PREAMBLE_MAX_S:
            break
        hook, n_new = b + 1, n_new + 1
    if hook > f:
        segs[0]["start"] = round(float(words[hook]["start"]), 3)
    info["hook_word"] = hook
    if hook > removed_from:
        info["preamble_removed_s"] = round(float(words[hook]["start"]) - float(words[removed_from]["start"]), 3)
    return segs, info


def hook_audio_report(
    timeline: list[dict], words: list[dict], audio: Audio | None, rules: HookAudioRules, info: dict[str, Any]
) -> dict[str, Any]:
    """Befund ``hook_audio`` (Modulkopf) aus der Zeitleiste des Plans (``source_in`` bis ``output_out``).

    Sprachbeginn: erstes Fenster mit Pegel über ``SPEECH_ONSET_RATIO`` mal dem Sprachpegel des ersten Wortes;
    ohne Audio der Beginn des ersten Wortes (``basis = "words"``). Hook-Beginn: Beginn des Hook-Wortes aus
    ``shift_preamble`` auf der Ausgabezeit."""
    def to_output(t: float) -> float | None:
        for e in timeline:
            if float(e["source_in"]) - 1e-6 <= t <= float(e["source_out"]) + 1e-6:
                return round(float(e["output_in"]) + max(0.0, t - float(e["source_in"])), 3)
        return None

    first_word = None
    for e in timeline:
        ids = edge_words(words, float(e["source_in"]), float(e["source_out"]))
        if ids is not None:
            first_word = ids[0]
            break
    hook_idx = info.get("hook_word")
    hook_idx = first_word if hook_idx is None else hook_idx
    hook_onset = to_output(float(words[hook_idx]["start"])) if hook_idx is not None else None
    speech_onset: float | None = None
    basis = "words"
    if audio is not None and first_word is not None:
        threshold = speech_level(audio, words[first_word]) * SPEECH_ONSET_RATIO
        horizon = rules.max_lead_s + rules.hook_window_s
        for e in timeline:
            if float(e["output_in"]) > horizon:
                break
            span = min(float(e["source_out"]), float(e["source_in"]) + horizon - float(e["output_in"]))
            hit = next((t for t, r, _h in frame_analysis(audio, float(e["source_in"]) + FRAME_S / 2.0, span) if r > threshold), None)
            if hit is not None:
                speech_onset = round(float(e["output_in"]) + max(0.0, hit - FRAME_S / 2.0 - float(e["source_in"])), 3)
                break
        basis = "audio"
    elif first_word is not None:
        speech_onset = to_output(float(words[first_word]["start"]))
    ok = (
        speech_onset is not None and hook_onset is not None
        and speech_onset <= rules.max_lead_s + 1e-6 and hook_onset <= rules.hook_window_s + 1e-6
    )  # fmt: skip
    return {
        "speech_onset_s": speech_onset,
        "hook_onset_s": hook_onset,
        "preamble_removed_s": float(info.get("preamble_removed_s") or 0.0),
        "ok": bool(ok),
        "basis": basis,
    }


__all__ = [
    "HOOK_AUDIO_SWITCH",
    "PROSODY_SWITCH",
    "Audio",
    "HookAudioRules",
    "PcmAudio",
    "ProsodyRules",
    "WavAudio",
    "find_breath",
    "frame_analysis",
    "hook_audio_report",
    "hook_audio_rules",
    "is_preamble",
    "preamble_phrases",
    "prosody_edges",
    "prosody_rules",
    "shift_preamble",
    "speech_level",
    "DOUBTFUL_TIMING_FACTOR",
    "EDGE_EPS_S",
    "ESTIMATED_TIME_SOURCES",
    "FULL_GAP_S",
    "GAP_WEIGHT",
    "PROB_WEIGHT",
    "UNKNOWN_PROB",
    "CutRules",
    "boundary_confidence",
    "check_transitions",
    "clamp_to_neighbors",
    "cut_rules",
    "edge_words",
    "pad_segments",
    "segment_confidence",
]
