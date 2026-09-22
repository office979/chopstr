"""Decision Log (Phase 5b, Grundsatz A3: kein Lernen ohne Decision Log).

Jede Entscheidung von Modell, Nutzer oder System landet in ``decision_log`` mit Merkmalen (``features``),
verworfenen Optionen (``alternatives``) und der gewählten Option (``chosen``). Die Lernschleife
(``learning.py``) und der Wochenreport lesen ausschließlich daraus und aus ``performance_feedback``.
Merkmale sind Zahlen, Muster und Strukturen, keine Transkriptzitate.
"""

from __future__ import annotations

from typing import Any

from . import db
from .pipeline import story_engine

DECISION_TYPES = (
    "candidate_proposed",
    "candidate_scored",
    "candidate_verdict",
    "hook_selected",
    "hook_variant_shown",
    "caption_preset",
    "reframe_strategy",
    "publish",
)
ACTOR_TYPES = ("ai", "user", "system")
REFRAME_STRATEGIES = ("talking_head", "two_speakers", "neutral", "slide_pip")


def record(
    conn: db.Connection,
    workspace_id: str,
    decision_type: str,
    features: dict[str, Any] | None,
    alternatives: list[Any] | None,
    chosen: dict[str, Any] | None,
    actor_type: str = "ai",
    brand_profile_id: str | None = None,
    source_id: str | None = None,
    candidate_id: str | None = None,
    clip_id: str | None = None,
    actor_id: str | None = None,
    model_id: str | None = None,
    prompt_version: str | None = None,
) -> str:
    """Schreibt eine ``decision_log``-Zeile und gibt ihre ID zurück."""
    if decision_type not in DECISION_TYPES:
        raise ValueError(f"Unbekannter Entscheidungstyp: {decision_type}")
    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"Unbekannter Akteur: {actor_type}")
    row = db.insert(
        conn,
        "decision_log",
        returning="id",
        workspace_id=workspace_id,
        brand_profile_id=brand_profile_id,
        source_id=source_id,
        candidate_id=candidate_id,
        clip_id=clip_id,
        decision_type=decision_type,
        features=db.jsonb(dict(features or {})),
        alternatives=db.jsonb(list(alternatives or [])),
        chosen=db.jsonb(dict(chosen or {})),
        actor_type=actor_type,
        actor_id=actor_id,
        model_id=model_id,
        prompt_version=prompt_version,
    )
    return str(row[0]) if row else ""


# -- Merkmale ------------------------------------------------------------------------------------
def candidate_features(cand: story_engine.CandidateResult, platform: str) -> dict[str, Any]:
    """Rubrik-Scores, Gewichte, Struktur, Länge, Plattform, Sprecherzahl, Gates, Flags eines Kandidaten."""
    rubric = dict(cand.rubric or {})
    scores = {k: int((rubric.get("scores") or {}).get(k, {}).get("value", 0) or 0) for k in story_engine.SCORE_KEYS}
    weights = {k: float((rubric.get("scores") or {}).get(k, {}).get("weight", 0) or 0) for k in story_engine.SCORE_KEYS}
    return {
        "scores": scores,
        "weights": weights,
        "total": float(cand.total),
        "structure": cand.structure,
        "duration_s": round(float(cand.end_s) - float(cand.start_s), 2),
        "platform": platform,
        "speakers": len(rubric.get("speakers") or []),
        "gates": {name: bool(g.get("passed")) for name, g in (cand.gates or {}).items()},
        "gate_passed": bool(cand.gate_passed),
        "risk_flags": list(cand.risk_flags or []),
        "story_graph_flags": len(cand.story_graph_flags or []),
        "repair_rounds": int((rubric.get("repair") or {}).get("rounds", 0) or 0),
    }


def record_detect_report(
    conn: db.Connection,
    workspace_id: str,
    source_id: str,
    brand_profile_id: str | None,
    report: story_engine.DetectReport,
    candidate_ids: list[str],
    platform: str,
) -> int:
    """``candidate_proposed`` je Vorschlag (behalten oder verworfen) und ``candidate_scored`` je Kandidat."""
    n = 0
    common = dict(
        workspace_id=workspace_id, brand_profile_id=brand_profile_id, source_id=source_id,
        model_id=report.model_id or None,
    )  # fmt: skip
    for cand, cid in zip(report.candidates, candidate_ids):
        feats = candidate_features(cand, platform)
        record(
            conn, decision_type="candidate_proposed", candidate_id=cid or None,
            features={"first_sent": cand.first_sent, "last_sent": cand.last_sent, "duration_s": feats["duration_s"], "structure": cand.structure},
            alternatives=[], chosen={"kept": True, "candidate_id": cid or None},
            prompt_version=report.prompt_versions[0] if report.prompt_versions else None, **common,
        )  # fmt: skip
        record(
            conn, decision_type="candidate_scored", candidate_id=cid or None,
            features=feats, alternatives=[],
            chosen={"candidate_id": cid or None, "total": feats["total"], "gate_passed": feats["gate_passed"]},
            prompt_version=cand.prompt_version, **common,
        )  # fmt: skip
        n += 2
    for d in report.discarded:
        record(
            conn, decision_type="candidate_proposed",
            features={k: d.get(k) for k in ("first_sent", "last_sent", "duration_s", "total") if k in d},
            alternatives=[], chosen={"kept": False, "reason": d.get("reason")},
            prompt_version=report.prompt_versions[0] if report.prompt_versions else None, **common,
        )  # fmt: skip
        n += 1
    return n


def record_copy_result(
    conn: db.Connection,
    workspace_id: str,
    clip_id: str,
    copy: Any,
    brand_profile_id: str | None = None,
    source_id: str | None = None,
    candidate_id: str | None = None,
    platform: str | None = None,
) -> list[str]:
    """Persistiert die Entscheidungen einer ``copy_engine.CopyResult`` (``hook_variant_shown``, ``hook_selected``).

    Aufruf gehört in ``activities/render.py`` direkt nach ``_write_hook_version`` (siehe README, Phase 5)."""
    ids = []
    for d in list(getattr(copy, "decisions", None) or []):
        feats = dict(d.get("features") or {})
        if platform and "platform" not in feats:
            feats["platform"] = platform
        ids.append(
            record(
                conn, workspace_id, d["decision_type"], feats, list(d.get("alternatives") or []), dict(d.get("chosen") or {}),
                actor_type=d.get("actor_type", "ai"), brand_profile_id=brand_profile_id, source_id=source_id,
                candidate_id=candidate_id, clip_id=clip_id, model_id=getattr(copy, "model_id", None),
                prompt_version=getattr(copy, "prompt_version", None),
            )  # fmt: skip
        )
    return ids


def record_reframe_strategy(
    conn: db.Connection,
    workspace_id: str,
    clip_id: str,
    plan: dict[str, Any],
    override: str | None = None,
    source_id: str | None = None,
    candidate_id: str | None = None,
    brand_profile_id: str | None = None,
) -> str:
    """``reframe_strategy``: gewählte Strategie aus ``plan["reframe"]``, andere Strategien als Alternativen.

    Aufruf gehört in ``activities/render.py`` nach ``render_plan.build_plan`` (Welle 5c hängt ihn ein)."""
    rf = dict(plan.get("reframe") or {})
    strategy = str(override or rf.get("strategy") or "neutral")
    features = {
        "strategy": strategy,
        "override": override,
        "aspect": plan.get("aspect"),
        "platform": plan.get("platform"),
        "confidence": rf.get("confidence"),
        "slide_region": rf.get("slide_region"),
        "notes": len(rf.get("notes") or []),
    }
    alternatives = [{"strategy": s} for s in REFRAME_STRATEGIES if s != strategy]
    return record(
        conn, workspace_id, "reframe_strategy", features, alternatives, {"strategy": strategy},
        actor_type="user" if override else "ai", brand_profile_id=brand_profile_id, source_id=source_id,
        candidate_id=candidate_id, clip_id=clip_id,
    )  # fmt: skip


__all__ = [
    "ACTOR_TYPES",
    "DECISION_TYPES",
    "REFRAME_STRATEGIES",
    "candidate_features",
    "record",
    "record_copy_result",
    "record_detect_report",
    "record_reframe_strategy",
]
