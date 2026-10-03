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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


__all__ = [
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
