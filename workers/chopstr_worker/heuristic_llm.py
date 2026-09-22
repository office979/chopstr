"""Heuristik-Provider ``local-heuristic``: bedient die drei Tool-Schemata der Story-Engine ohne Netz.

Das ist KEIN Ersatz für ein Sprachmodell. Der Provider existiert, damit Entwicklung, Tests und Demos
ohne LLM-Zugang durch die ganze Kette laufen (Kandidaten entstehen, die UI hat Daten). Die Auswahl
beruht auf einfachen Merkmalen: Diskursmarker (``signals.DISCOURSE_MARKERS``), Zahlen, Fragen,
Kontrastmarker, Länge. Produktion braucht einen echten EU-Provider (``bedrock-eu``, ``mistral-eu``,
``selfhost-eu``). Ergebnisse tragen ``model_id = "heuristic-v1"`` und ``risk_flags`` enthält
``heuristic_only``.

Der Provider liest nur den gerenderten Prompt (Zeilen ``[idx] (Sprecher) Text``). Zeiten kennt er
nicht; Längen werden aus der Wortzahl geschätzt (``WORDS_PER_SECOND``). Die harten Längen-Grenzen
prüft die Story-Engine anschließend mit den echten Wortzeiten.

Alles hier ist deterministisch: gleicher Prompt, gleiche Antwort.
"""

from __future__ import annotations

import re

from .pipeline import dach_nlp
from .pipeline.signals import DISCOURSE_MARKERS
from .pipeline.story_graph import CONTRAST_MARKERS

MODEL_ID = "heuristic-v1"
WORDS_PER_SECOND = 2.5  # ruhiges Sprechtempo Deutsch, etwa 150 Wörter pro Minute
PROPOSE_MIN_S = 15.0
PROPOSE_TARGET_S = 30.0
PROPOSE_MAX_S = 60.0
PROPOSE_MAX_MOMENTS = 3
EVIDENCE_WORDS = 8

_LINE = re.compile(r"^\[(\d+)\]\s+\(([^)]*)\)\s*(.*)$")
_NUMBER = re.compile(r"\d[\d.,]*")

CONTEXT_STARTS = (
    "und ", "aber ", "also ", "deshalb ", "deswegen ", "weil ", "dann ", "denn ", "sondern ", "trotzdem ",
    "wie gesagt", "das heißt ", "außerdem ", "dazu ", "darum ", "danach ", "davor ",
)  # fmt: skip
REFERENCE_PHRASES = (
    "wie gesagt", "wie vorhin", "wie erwähnt", "das von vorhin", "diese grafik", "dieses bild",
    "wie ihr seht", "wie sie sehen", "hier oben", "hier unten", "die folie",
)  # fmt: skip
SENSITIVE_TERMS = (
    "diagnose", "therapie", "medikament", "krankheit", "symptom", "heilung", "rendite", "aktie", "aktien",
    "investieren", "investment", "kredit", "steuern sparen", "anwalt", "klage", "gericht", "haftung",
)  # fmt: skip
CONTRAST_WORDS = re.compile(r"\b(aber|allerdings|jedoch|wobei|trotzdem)\b")


def parse_numbered(text: str) -> list[dict]:
    """Zeilen ``[idx] (Sprecher) Text`` aus dem gerenderten Prompt."""
    out = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            out.append({"idx": int(m.group(1)), "speaker": m.group(2), "text": m.group(3).strip()})
    return out


def estimate_seconds(sents: list[dict]) -> float:
    n = sum(len(s["text"].split()) for s in sents)
    return n / WORDS_PER_SECOND


def _evidence(sent: dict) -> str:
    """Wörtlicher Satzanfang (maximal ``EVIDENCE_WORDS`` Wörter), damit der Beleg im Clip vorkommt."""
    return " ".join(sent["text"].split()[:EVIDENCE_WORDS])


def _markers_in(low: str) -> list[str]:
    return [m for m in DISCOURSE_MARKERS if m in low]


def _anchor_score(sent: dict) -> float:
    low = sent["text"].lower()
    score = 0.0
    score += 2.0 * min(len(_markers_in(low)), 2)
    if _NUMBER.search(sent["text"]):
        score += 1.0
    if sent["text"].rstrip().endswith("?"):
        score += 1.0
    if any(m in low for m in CONTRAST_MARKERS):
        score += 1.0
    return score


def _structure_for(span: list[dict]) -> str:
    first_low = span[0]["text"].lower()
    text_low = " ".join(s["text"] for s in span).lower()
    if span[0]["text"].rstrip().endswith("?"):
        return "tension_first"
    if _NUMBER.search(span[0]["text"]):
        return "payoff_first"
    if any(m in first_low for m in ("ich war", "wir haben damals", "der moment, als", "und dann")):
        return "hook_build_payoff"
    if any(m in text_low for m in ("der fehler war", "mein größter fehler", "was ich gelernt habe")):
        return "decision_story"
    if any(m in text_low for m in ("zum beispiel", "konkret heißt das", "das heißt konkret", "erstens", "zweitens")):
        return "how_to_list"
    return "hook_build_payoff"


def propose_moments(user: str) -> dict:
    """Bis zu drei nicht überlappende Satz-Spannen (geschätzt 15 bis 60 Sekunden) um Marker, Zahlen, Fragen."""
    sents = parse_numbered(user)
    if not sents:
        return {"moments": []}
    anchors = sorted(((_anchor_score(s), i) for i, s in enumerate(sents)), key=lambda x: (-x[0], x[1]))
    chosen: list[tuple[int, int]] = []
    moments = []
    for score, i in anchors:
        if score <= 0 or len(moments) >= PROPOSE_MAX_MOMENTS:
            break
        if any(a <= i <= b for a, b in chosen):
            continue
        a, b = i, i
        while estimate_seconds(sents[a : b + 1]) < PROPOSE_TARGET_S and b + 1 < len(sents):
            if estimate_seconds(sents[a : b + 2]) > PROPOSE_MAX_S:
                break
            if any(x <= b + 1 <= y for x, y in chosen):
                break
            b += 1
        while estimate_seconds(sents[a : b + 1]) < PROPOSE_MIN_S and a > 0:
            if estimate_seconds(sents[a - 1 : b + 1]) > PROPOSE_MAX_S:
                break
            if any(x <= a - 1 <= y for x, y in chosen):
                break
            a -= 1
        if estimate_seconds(sents[a : b + 1]) < PROPOSE_MIN_S:
            continue
        chosen.append((a, b))
        span = sents[a : b + 1]
        low = " ".join(s["text"] for s in span).lower()
        reasons = []
        markers = _markers_in(low)
        if markers:
            reasons.append(f"Diskursmarker „{markers[0]}“")
        if _NUMBER.search(" ".join(s["text"] for s in span)):
            reasons.append("Zahl im Abschnitt")
        if any(s["text"].rstrip().endswith("?") for s in span):
            reasons.append("Frage im Abschnitt")
        why = "Heuristik ohne Sprachmodell: " + (", ".join(reasons) if reasons else "auffälliger Abschnitt") + "."
        moments.append(
            {"first_sent": span[0]["idx"], "last_sent": span[-1]["idx"], "structure": _structure_for(span), "why": why}
        )
    return {"moments": moments}


def score_clip(user: str) -> dict:
    """Rubrik aus einfachen Merkmalen; Belege sind wörtliche Satzanfänge aus dem Kandidaten."""
    sents = parse_numbered(user)
    if not sents:
        sents = [{"idx": 0, "speaker": "?", "text": user.strip() or "-"}]
    text = " ".join(s["text"] for s in sents)
    low = text.lower()
    first, last = sents[0], sents[-1]
    first_low = first["text"].lower()
    est_s = estimate_seconds(sents)
    numbers = _NUMBER.findall(text)
    markers = _markers_in(low)
    question_start = first["text"].rstrip().endswith("?")
    has_question = any(s["text"].rstrip().endswith("?") for s in sents)
    contrast = bool(CONTRAST_WORDS.search(low)) or any(m in low for m in CONTRAST_MARKERS)
    tokens = set(re.findall(r"[a-zäöüß]+", low))
    negation = bool(tokens & dach_nlp.NEGATIONS)
    good_length = 20.0 <= est_s <= 60.0

    def clamp(v: float) -> int:
        return int(max(0, min(10, round(v))))

    hook = clamp(3 + (3 if question_start else 0) + (3 if any(m in first_low for m in DISCOURSE_MARKERS) else 0)
                 + (1 if len(first["text"].split()) <= 15 else 0) + (1 if _NUMBER.search(first["text"]) else 0))  # fmt: skip
    payoff = clamp(3 + 2 * min(len(numbers), 2) + (2 if markers else 0) + (1 if good_length else 0))
    specificity = clamp(2 + 2 * min(len(numbers), 3) + (1 if "zum beispiel" in low or "konkret" in low else 0)
                        + (1 if len(re.findall(r"(?<!^)(?<![.!?] )\b[A-ZÄÖÜ][a-zäöüß]{3,}", text)) >= 3 else 0))  # fmt: skip
    tension = clamp(2 + (3 if has_question else 0) + (3 if contrast else 0) + (1 if negation else 0))
    audience_fit = clamp(5 + (1 if good_length else 0) + (1 if numbers else 0))

    number_sent = next((s for s in sents if _NUMBER.search(s["text"])), last)
    tension_sent = next((s for s in sents if s["text"].rstrip().endswith("?") or CONTRAST_WORDS.search(s["text"].lower())), first)

    unresolved = [p for p in REFERENCE_PHRASES if p in low]
    needs_earlier = first_low.startswith(CONTEXT_STARTS)
    ends_before = dach_nlp.ends_with_open_loop(last["text"]) or last["text"].rstrip().endswith("?")
    sensitive = any(t in low for t in SENSITIVE_TERMS)

    parts = [f"{len(numbers)} Zahlen" if numbers else "keine Zahlen"]
    if question_start:
        parts.append("Frage am Anfang")
    if contrast:
        parts.append("Kontrastmarker")
    parts.append(f"geschätzt {round(est_s)} Sekunden")
    return {
        "unresolved_references": unresolved,
        "needs_earlier_context": bool(needs_earlier),
        "ends_before_answer": bool(ends_before),
        "hook": hook,
        "hook_evidence": _evidence(first),
        "payoff": payoff,
        "payoff_evidence": _evidence(number_sent),
        "specificity": specificity,
        "specificity_evidence": _evidence(number_sent),
        "tension": tension,
        "tension_evidence": _evidence(tension_sent),
        "audience_fit": audience_fit,
        "audience_fit_evidence": _evidence(first),
        "is_humor": False,
        "sensitive_topic": sensitive,
        "suggested_title_card": "",
        "why": "Heuristik ohne Sprachmodell: " + ", ".join(parts) + ".",
    }


def confirm_qualification(user: str) -> dict:
    """Ohne Sprachmodell nicht entscheidbar: ``misleading_without = None``, der Aufrufer setzt ``confirmed = null``."""
    return {
        "misleading_without": None,
        "reason": "Ohne Sprachmodell nicht prüfbar, Mensch entscheidet",
        "repair": "none",
    }


HANDLERS = {
    "propose_moments": propose_moments,
    "score_clip": score_clip,
    "confirm_qualification": confirm_qualification,
}


def answer(tool_name: str, user: str, schema: dict | None = None) -> dict:
    """Deterministische Antwort für ein bekanntes Tool-Schema."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        raise RuntimeError(f"Heuristik-Provider kennt das Tool {tool_name} nicht")
    return handler(user)


__all__ = [
    "HANDLERS",
    "MODEL_ID",
    "WORDS_PER_SECOND",
    "answer",
    "confirm_qualification",
    "estimate_seconds",
    "parse_numbered",
    "propose_moments",
    "score_clip",
]
