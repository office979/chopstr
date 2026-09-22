"""Story-Engine (Phase 2): LLM schlägt Momente vor, Rubrik bewertet mit Gates und Belegzitaten.

Zweistufig, damit es bei 90-Min-Podcasts bezahlbar bleibt:
  Stufe A (pro Kapitel): ``propose`` mit ``propose_moments_v1``
  Stufe B (pro Vorschlag): ``score`` mit ``score_clip_v1``; bei offenem Kontext erweitert
                           ``score_with_repair`` die Grenzen und bewertet neu (max. 2 Runden).

Kein Provider-Client auf Modulebene: alle Aufrufe laufen über ``providers_llm.LLM`` (Residency-Guard)
und ``prompts.load`` (versionierte Prompts).
"""

from __future__ import annotations

from typing import Any

from .. import prompts
from ..providers_llm import LLM
from .segment import Sentence, numbered

STRUCTURES = ["payoff_first", "tension_first", "hook_build_payoff", "decision_story", "how_to_list", "loop"]

PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_sent": {"type": "integer"},
                    "last_sent": {"type": "integer"},
                    "structure": {"type": "string", "enum": STRUCTURES},
                    "why": {"type": "string"},
                },
                "required": ["first_sent", "last_sent", "structure", "why"],
            },
        }
    },
    "required": ["moments"],
}

RUBRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "unresolved_references": {"type": "array", "items": {"type": "string"}},
        "needs_earlier_context": {"type": "boolean"},
        "ends_before_answer": {"type": "boolean"},
        "hook": {"type": "integer", "minimum": 0, "maximum": 10},
        "hook_evidence": {"type": "string"},
        "payoff": {"type": "integer", "minimum": 0, "maximum": 10},
        "payoff_evidence": {"type": "string"},
        "specificity": {"type": "integer", "minimum": 0, "maximum": 10},
        "specificity_evidence": {"type": "string"},
        "tension": {"type": "integer", "minimum": 0, "maximum": 10},
        "tension_evidence": {"type": "string"},
        "audience_fit": {"type": "integer", "minimum": 0, "maximum": 10},
        "audience_fit_evidence": {"type": "string"},
        "is_humor": {"type": "boolean"},
        "sensitive_topic": {"type": "boolean"},
        "suggested_title_card": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": [
        "unresolved_references", "needs_earlier_context", "ends_before_answer", "hook", "hook_evidence",
        "payoff", "payoff_evidence", "specificity", "specificity_evidence", "tension", "audience_fit",
        "is_humor", "suggested_title_card", "why",
    ],  # fmt: skip
}

DEFAULT_WEIGHTS = {"hook": 0.30, "payoff": 0.25, "specificity": 0.20, "tension": 0.15, "audience_fit": 0.10}


def system_prompt() -> str:
    return prompts.load("system_editor").render()


def weights(p: prompts.Prompt | None = None) -> dict[str, float]:
    p = p or prompts.load("score_clip")
    w = p.meta.get("weights") or {}
    return {k: float(w.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}


def propose(chapter: list[Sentence], brief: dict[str, Any], llm: LLM) -> list[dict]:
    p = prompts.load("propose_moments")
    user = p.render(
        audience=brief.get("audience"),
        wanted=brief.get("wanted"),
        exclude=brief.get("exclude"),
        platform=brief.get("platform", "linkedin"),
        chapter_numbered=numbered(chapter),
    )
    out = llm.structured(system_prompt(), user, PROPOSE_SCHEMA, p.tool or "propose_moments", p.prompt_version, job_type="llm_propose")
    valid_idx = {s.idx for s in chapter}
    moments = []
    for m in out.get("moments", []):
        if m.get("first_sent") in valid_idx and m.get("last_sent") in valid_idx and m["first_sent"] <= m["last_sent"]:
            m["prompt_version"] = p.prompt_version
            moments.append(m)
    return moments


def _evidence_grounded(r: dict, text: str) -> list[str]:
    """Belegzitate müssen wörtlich im Kandidaten vorkommen (Halluzinationsschutz)."""
    issues = []
    low = text.lower()
    for key in ("hook_evidence", "payoff_evidence", "specificity_evidence", "tension_evidence", "audience_fit_evidence"):
        ev = str(r.get(key, "") or "").strip()
        if ev and ev.lower() not in low:
            issues.append(key)
    return issues


def score(span_sents: list[Sentence], brief: dict[str, Any], llm: LLM) -> dict:
    p = prompts.load("score_clip")
    text = " ".join(s.text for s in span_sents)
    user = p.render(audience=brief.get("audience"), platform=brief.get("platform", "linkedin"), candidate_numbered=numbered(span_sents))
    r = llm.structured(system_prompt(), user, RUBRIC_SCHEMA, p.tool or "score_clip", p.prompt_version, job_type="llm_score")
    w = weights(p)
    r["gate_passed"] = not (r["needs_earlier_context"] or r["ends_before_answer"] or r["unresolved_references"])
    r["total"] = round(sum(float(r.get(k, 0)) * wk for k, wk in w.items()), 2)
    r["needs_human"] = bool(r.get("is_humor")) or bool(r.get("sensitive_topic"))
    r["ungrounded_evidence"] = _evidence_grounded(r, text)
    r["prompt_version"] = p.prompt_version
    r["model_id"] = llm.model()
    return r


def score_with_repair(sents: list[Sentence], first: int, last: int, brief: dict[str, Any], llm: LLM, max_rounds: int = 2) -> dict:
    """Erweitert die Grenzen, solange Kontext fehlt (erst nach vorne, dann nach hinten)."""
    r: dict = {}
    for _ in range(max_rounds + 1):
        r = score(sents[first : last + 1], brief, llm)
        r.update(first_sent=first, last_sent=last, start=sents[first].start, end=sents[last].end)
        if r["gate_passed"]:
            return r
        moved = False
        if (r["needs_earlier_context"] or r["unresolved_references"]) and first > 0:
            first, moved = first - 1, True
        if r["ends_before_answer"] and last < len(sents) - 1:
            last, moved = last + 1, True
        if not moved:
            break
    r["repair_failed"] = True  # UI zeigt Titelkarten-Vorschlag statt Clip zu verwerfen
    return r


__all__ = [
    "DEFAULT_WEIGHTS",
    "PROPOSE_SCHEMA",
    "RUBRIC_SCHEMA",
    "STRUCTURES",
    "propose",
    "score",
    "score_with_repair",
    "system_prompt",
    "weights",
]
