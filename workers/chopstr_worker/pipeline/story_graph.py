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


def find_later_qualifications(sents: list[Sentence], clip_first: int, clip_last: int) -> list[dict]:
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
    p = prompts.load("story_graph_confirm")
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


__all__ = ["CONFIRM_SCHEMA", "CONTRAST_MARKERS", "build_confirm_prompt", "claims_in", "confirm", "find_later_qualifications"]
