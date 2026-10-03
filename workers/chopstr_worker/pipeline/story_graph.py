"""Story-Graph light (Phase 2): findet Stellen NACH einem Clip, die dessen Aussage einschränken.

Ein Clip kann formal sauber geschnitten und trotzdem irreführend sein, wenn 20 Sekunden später
„Das heißt aber nicht, dass ..." kommt.

Stufe 1 (billig, deterministisch): Kontrastmarker plus lexikalische Überlappung im Folgefenster.
Stufe 2 (nur bei Treffer): LLM-Urteil über ``story_graph_confirm_v1`` (``confirm`` unten).
Ohne spaCy werden statt Lemmata einfache Wortstämme verglichen.
"""

from __future__ import annotations

import re
from typing import Any

from .. import prompts
from . import dach_nlp
from .segment import Sentence

CONTRAST_MARKERS = (
    "das heißt aber nicht", "das heißt nicht", "das bedeutet nicht", "wobei man sagen muss",
    "allerdings", "aber natürlich", "außer", "nur wenn", "es sei denn", "fairerweise",
    "um das einzuordnen", "nicht falsch verstehen", "das gilt nicht", "in unserem fall",
    "bei uns war das", "das ist aber die ausnahme", "das gilt nur", "mit einer einschränkung",
)  # fmt: skip
# Korrekturmarker (AP4, nur Regel v2): der Sprecher nimmt eine eigene Aussage zurück.
CORRECTION_MARKERS = (
    "ich korrigiere mich", "das stimmt so nicht", "ich hab mich vertan", "ich habe mich vertan",
    "nein, falsch", "genauer gesagt", "um das richtigzustellen", "muss ich korrigieren",
)  # fmt: skip
LOOKAHEAD_S = 60.0
MIN_OVERLAP = 0.15

CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {
        "misleading_without": {"type": "boolean"},
        "reason": {"type": "string"},
        "repair": {"type": "string", "enum": ["extend", "overlay", "none"]},
    },
    "required": ["misleading_without", "reason"],
}

_SUFFIXES = ("ungen", "heiten", "keiten", "lich", "isch", "ung", "heit", "keit", "en", "er", "es", "em", "e", "n", "s")


def _stem(tok: str) -> str:
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def _lemmas(text: str) -> set[str]:
    pipe = dach_nlp.nlp()
    if pipe is not None:
        doc = pipe(text)
        return {t.lemma_.lower() for t in doc if t.pos_ in ("NOUN", "PROPN", "VERB", "ADJ") and len(t) > 3}
    return {_stem(t) for t in re.findall(r"[a-zäöüß]+", text.lower()) if len(t) > 3}


def lexical_overlap(clip_text: str, later_text: str) -> float:
    """Anteil der Inhaltswörter von ``later_text``, die auch in ``clip_text`` stehen (wie im Story-Graph)."""
    lem = _lemmas(later_text)
    return len(_lemmas(clip_text) & lem) / max(len(lem), 1)


def _marker_tokens(marker: str) -> tuple[str, ...]:
    return tuple(t for t in (dach_nlp.core_token(x) for x in marker.split()) if t)


def find_marker(text: str, markers: tuple[str, ...]) -> str | None:
    """Erster Marker aus ``markers``, der als ganze Wortfolge in ``text`` steht („außer“ trifft nicht
    „außerdem“, Satzzeichen zählen nicht)."""
    toks = [t for t in (dach_nlp.core_token(x) for x in text.split()) if t]
    for m in markers:
        mt = _marker_tokens(m)
        if mt and any(tuple(toks[k : k + len(mt)]) == mt for k in range(len(toks) - len(mt) + 1)):
            return m
    return None


def _find_later_qualifications_v2(sents: list[Sentence], clip_first: int, clip_last: int) -> list[dict]:
    """Regel v2: Marker an Wortgrenzen, zusätzlich Korrekturmarker. Bei einer Korrektur zählt für den Bezug
    auch der Satz danach, weil die Korrektur oft erst dort sagt, was sie richtigstellt."""
    clip_text = " ".join(s.text for s in sents[clip_first : clip_last + 1])
    end_t = sents[clip_last].end
    hits = []
    later = sents[clip_last + 1 :]
    for n, s in enumerate(later):
        if s.start - end_t > LOOKAHEAD_S:
            break
        marker = find_marker(s.text, CORRECTION_MARKERS)
        kind = "correction"
        if marker is None:
            marker, kind = find_marker(s.text, CONTRAST_MARKERS), "contrast"
        if not marker:
            continue
        text = s.text
        if kind == "correction" and n + 1 < len(later):
            text = f"{s.text} {later[n + 1].text}"
        overlap = lexical_overlap(clip_text, text)
        if overlap >= MIN_OVERLAP:
            hits.append(
                {
                    "sentence_idx": s.idx,
                    "seconds_after": round(s.start - end_t, 1),
                    "marker": marker,
                    "text": s.text,
                    "overlap": round(overlap, 2),
                    "suggestion": f"Clip bis Satz {s.idx} verlängern oder Einschränkung als Text einblenden",
                    "kind": kind,
                }
            )
    return hits


def find_later_qualifications(sents: list[Sentence], clip_first: int, clip_last: int, rule: str = "v1") -> list[dict]:
    """Spätere Einschränkungen nach dem Clip. ``rule="v1"`` ist das Verhalten vor AP4 (Teilstring-Abgleich),
    ``rule="v2"`` gleicht an Wortgrenzen ab und kennt Korrekturmarker (``kind``: contrast oder correction)."""
    if rule == "v2":
        return _find_later_qualifications_v2(sents, clip_first, clip_last)
    clip_text = " ".join(s.text for s in sents[clip_first : clip_last + 1])
    clip_lem = _lemmas(clip_text)
    end_t = sents[clip_last].end
    hits = []
    for s in sents[clip_last + 1 :]:
        if s.start - end_t > LOOKAHEAD_S:
            break
        low = s.text.lower()
        marker = next((m for m in CONTRAST_MARKERS if m in low), None)
        if not marker:
            continue
        lem = _lemmas(s.text)
        overlap = len(clip_lem & lem) / max(len(lem), 1)
        if overlap >= MIN_OVERLAP:
            hits.append(
                {
                    "sentence_idx": s.idx,
                    "seconds_after": round(s.start - end_t, 1),
                    "marker": marker,
                    "text": s.text,
                    "overlap": round(overlap, 2),
                    "suggestion": f"Clip bis Satz {s.idx} verlängern oder Einschränkung als Text einblenden",
                }
            )
    return hits


def build_confirm_prompt(clip_text: str, later_text: str, seconds_after: float) -> tuple[str, prompts.Prompt]:
    p = prompts.load_pinned("story_graph_confirm")
    return p.render(clip_text=clip_text, later_text=later_text, seconds_after=round(seconds_after)), p


def confirm(llm, clip_text: str, later_text: str, seconds_after: float) -> dict[str, Any]:
    """Stufe 2: LLM bestätigt oder verwirft den Treffer."""
    from .story_score import system_prompt

    user, p = build_confirm_prompt(clip_text, later_text, seconds_after)
    out = llm.structured(system_prompt(), user, CONFIRM_SCHEMA, p.tool or "confirm_qualification", p.prompt_version, job_type="llm_score")
    out["prompt_version"] = p.prompt_version
    return out


def claims_in(text: str) -> list[str]:
    """Grobe Claim-Extraktion für Grounding: Sätze mit Zahlen, Superlativen oder Kausalbehauptungen."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\d|immer|nie|jede[rsn]?|alle|garantiert|bewiesen|weil|dadurch", sent.lower()):
            out.append(sent.strip())
    return out


__all__ = [
    "CONFIRM_SCHEMA",
    "CONTRAST_MARKERS",
    "CORRECTION_MARKERS",
    "build_confirm_prompt",
    "claims_in",
    "confirm",
    "find_later_qualifications",
    "find_marker",
    "lexical_overlap",
]
