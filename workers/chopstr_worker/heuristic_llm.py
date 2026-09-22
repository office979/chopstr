"""Heuristik-Provider ``local-heuristic``: bedient die Tool-Schemata der Story-Engine und der Copy ohne Netz.

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


# -- Phase 3: Copy (Hooks, Post-Captions) ------------------------------------------------------------
_ADDRESS = re.compile(r"Anrede:\s*(DU|SIE|du|sie|Du|Sie)\b")
_PLATFORM = re.compile(r"für\s+(tiktok|reels|shorts|linkedin)\b", re.IGNORECASE)
_HOOK_ONSCREEN = re.compile(r"nicht wörtlich:\s*(.*)")
_NUMBER_PHRASE = re.compile(r"\d[\d.,]*(?:\s?(?:%|€|Prozent|Euro|Franken|Jahre|Jahren|Tage|Stunden|Minuten|Kunden|Mitarbeiter|Leute|Mal))?")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
SPOKEN_MAX_WORDS = 12
ONSCREEN_MAX_WORDS = 9
HOOK_PATTERNS = ("identity_call", "contrarian", "open_loop", "results_first", "mistake_warning")


def clip_text_of(user: str) -> str:
    """Text nach der letzten Zeile ``CLIP:`` im gerenderten Prompt."""
    marker = "CLIP:"
    idx = user.rfind(marker)
    return user[idx + len(marker) :].strip() if idx >= 0 else user.strip()


def address_of(user: str) -> str:
    """Anrede aus dem Prompt (``du`` | ``sie``), Default ``du``."""
    m = _ADDRESS.search(user)
    return m.group(1).lower() if m else "du"


def sentences_of(text: str) -> list[str]:
    return [x.strip() for x in _SENT_SPLIT.split(" ".join(text.split())) if x.strip()]


def _core(sentence: str, max_words: int) -> str:
    """Satzanfang ohne Schlusszeichen, maximal ``max_words`` Wörter (nur Wörter aus dem Clip)."""
    toks = sentence.split()
    cut = toks[:max_words]
    out = " ".join(cut).rstrip(".,;:!?")
    return out[:1].upper() + out[1:] if out else out


def _fit(prefix: str, sentence: str, limit: int, suffix: str = "") -> str:
    """``prefix`` plus Satzanfang, so gekürzt, dass die Wortzahl ``limit`` nicht überschreitet."""
    used = len(prefix.split()) + len(suffix.split())
    core = _core(sentence, max(1, limit - used))
    text = f"{prefix} {core}".strip()
    return f"{text}{suffix}" if suffix else text


def write_hooks(user: str) -> dict:
    """Fünf Hook-Varianten aus Satzanfängen, erster Zahl und Kontrastmarker des Clips. Keine neuen Zahlen."""
    clip = clip_text_of(user)
    address = address_of(user)
    sents = sentences_of(clip) or [clip or "-"]
    first = sents[0]
    number = _NUMBER_PHRASE.search(clip)
    number_sent = next((x for x in sents if _NUMBER.search(x)), first)
    contrast_sent = next((x for x in sents if CONTRAST_WORDS.search(x.lower())), None)
    du = address == "du"
    variants = [
        {
            "pattern": "identity_call",
            "spoken": _fit("Du kennst das sicher:" if du else "Sie kennen das sicher:", first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Kennst du das:" if du else "Kennen Sie das:", first, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "contrarian",
            "spoken": _fit("Das Gegenteil stimmt:", contrast_sent or first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Das Gegenteil:", contrast_sent or first, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "open_loop",
            "spoken": _fit("Was dahinter steckt:", first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Was dahinter steckt:", first, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "results_first",
            "spoken": _fit(f"{number.group(0).strip()}:" if number else "Das Ergebnis:", number_sent, SPOKEN_MAX_WORDS),
            "onscreen": _fit(f"{number.group(0).strip()}:" if number else "Das Ergebnis:", number_sent, ONSCREEN_MAX_WORDS),
        },
        {
            "pattern": "mistake_warning",
            "spoken": _fit("Dieser Fehler kostet dich viel:" if du else "Dieser Fehler kostet Sie viel:", first, SPOKEN_MAX_WORDS),
            "onscreen": _fit("Dieser Fehler kostet:", first, ONSCREEN_MAX_WORDS),
        },
    ]
    return {"variants": variants}


def write_post_caption(user: str) -> dict:
    """Post-Text pro Plattform nur aus Sätzen des Clips; CTA in der Anrede des Profils."""
    clip = clip_text_of(user)
    address = address_of(user)
    m = _PLATFORM.search(user.split("CLIP:", 1)[0])
    platform = m.group(1).lower() if m else "linkedin"
    hook = (_HOOK_ONSCREEN.search(user.split("CLIP:", 1)[0]) or [None, ""])[1]
    hook = hook.strip() if isinstance(hook, str) else ""
    sents = [x for x in sentences_of(clip) if x != hook] or [clip or "-"]
    du = address == "du"
    if platform in ("tiktok", "reels"):
        text = "\n".join(sents[:2])
        cta = "Was ist deine Erfahrung damit?" if du else "Was ist Ihre Erfahrung damit?"
    elif platform == "shorts":
        title = _core(sents[0], 8)
        if len(title) > 60:
            title = title[:57].rstrip() + "..."
        text = f"{title}\n{sents[1] if len(sents) > 1 else sents[0]}"
        cta = "Mehr dazu im ganzen Gespräch."
    else:
        statement = _core(sents[0], 8)
        paragraphs = [statement, *sents[1:4]]
        text = "\n\n".join(paragraphs)
        cta = "Wie siehst du das?" if du else "Wie sehen Sie das?"
    return {"text": text, "cta": cta}


HANDLERS = {
    "propose_moments": propose_moments,
    "score_clip": score_clip,
    "confirm_qualification": confirm_qualification,
    "write_hooks": write_hooks,
    "write_post_caption": write_post_caption,
}


def answer(tool_name: str, user: str, schema: dict | None = None) -> dict:
    """Deterministische Antwort für ein bekanntes Tool-Schema."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        raise RuntimeError(f"Heuristik-Provider kennt das Tool {tool_name} nicht")
    return handler(user)


__all__ = [
    "HANDLERS",
    "HOOK_PATTERNS",
    "MODEL_ID",
    "ONSCREEN_MAX_WORDS",
    "SPOKEN_MAX_WORDS",
    "WORDS_PER_SECOND",
    "address_of",
    "answer",
    "clip_text_of",
    "confirm_qualification",
    "estimate_seconds",
    "parse_numbered",
    "propose_moments",
    "score_clip",
    "sentences_of",
    "write_hooks",
    "write_post_caption",
]
