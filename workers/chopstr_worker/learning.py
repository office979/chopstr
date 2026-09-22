"""Lernschleife (Phase 5b): Rubrik-Gewichte je Markenprofil und Hook-Muster-Statistik.

Rubrik-Gewichte: Ridge-Regression der fünf Scores (``hook``, ``payoff``, ``specificity``, ``tension``,
``audience_fit``) auf ein Ziel aus Nutzerurteil (accepted = 1, rejected = 0, edited = 0,5) und Reward:
``0,6 * Urteil + 0,4 * Reward`` wenn ein Reward vorliegt, sonst nur das Urteil. Ergebnis auf [0,05, 0,5]
begrenzt und auf Summe 1 normalisiert, erst ab 20 Entscheidungen. Landet in ``brand_profiles.learned_weights``
als ``{ weights, n, fitted_at, r2 }`` mit Audit ``learning.updated``; ``story_engine.resolve_weights`` liest es.

Hook-Muster: ``hook_pattern_stats`` (shown, chosen, reward_sum, reward_n) für Thompson Sampling.
``update_hook_stats`` zählt inkrementell, ``rebuild_hook_stats`` rechnet nächtlich alles aus ``decision_log``
und ``performance_feedback`` neu (idempotent). ``thompson_order`` liefert die Reihenfolge der fünf Muster.
Alle Entscheidungen kommen aus dem Decision Log (Grundsatz A3).
"""

from __future__ import annotations

import json
import logging
import random
from datetime import UTC, datetime
from typing import Any

from . import db
from .pipeline.copy_engine import HOOK_PATTERNS
from .pipeline.story_engine import SCORE_KEYS

log = logging.getLogger("chopstr.learning")

MIN_DECISIONS = 20
WEIGHT_MIN = 0.05
WEIGHT_MAX = 0.5
RIDGE_LAMBDA = 1.0
VERDICT_SCORES = {"accepted": 1.0, "rejected": 0.0, "edited": 0.5}
TARGET_VERDICT_SHARE = 0.6
TARGET_REWARD_SHARE = 0.4
REWARD_CAP = 3.0

SQL_VERDICT_ROWS = (
    "select c.id, c.rubric, c.human_verdict from candidates c join sources s on s.id = c.source_id "
    "where s.brand_profile_id = %s and c.human_verdict is not null"
)
SQL_REWARD_BY_CANDIDATE = (
    "select cl.candidate_id, max(f.reward) from performance_feedback f join clips cl on cl.id = f.clip_id "
    "join sources s on s.id = cl.source_id where s.brand_profile_id = %s and f.metric_window = '7d' "
    "and f.reward is not null and cl.candidate_id is not null group by cl.candidate_id"
)
SQL_PROFILE_WORKSPACE = "select workspace_id from brand_profiles where id = %s"
SQL_HOOK_STAT = "select shown, chosen, reward_sum, reward_n from hook_pattern_stats where brand_profile_id = %s and pattern = %s"
SQL_HOOK_STATS = "select pattern, shown, chosen, reward_sum, reward_n from hook_pattern_stats where brand_profile_id = %s"
SQL_HOOK_DECISIONS = (
    "select decision_type, features, chosen from decision_log where brand_profile_id = %s "
    "and decision_type in ('hook_variant_shown', 'hook_selected')"
)
SQL_HOOK_REWARDS = (
    "select f.clip_id, f.reward from performance_feedback f join clips cl on cl.id = f.clip_id "
    "join sources s on s.id = cl.source_id where s.brand_profile_id = %s and f.metric_window = '7d' and f.reward is not null"
)
SQL_HOOK_PATTERN_OF_CLIP = "select pattern from hook_versions where clip_id = %s order by version desc limit 1"
SQL_ACTIVE_PROFILES = (
    "select distinct s.brand_profile_id from sources s join candidates c on c.source_id = s.id "
    "where s.brand_profile_id is not null and c.human_verdict is not null"
)


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def verdict_score(verdict: str | None) -> float | None:
    return VERDICT_SCORES.get(str(verdict or "").lower())


def target_value(verdict: str | None, reward: float | None) -> float | None:
    """Ziel je Entscheidung: 0,6 Urteil + 0,4 Reward (Reward auf [0, 3] gedeckelt), sonst nur Urteil."""
    v = verdict_score(verdict)
    if v is None:
        return None
    if reward is None:
        return v
    r = max(0.0, min(REWARD_CAP, float(reward)))
    return TARGET_VERDICT_SHARE * v + TARGET_REWARD_SHARE * r


def scores_from_rubric(rubric: Any) -> dict[str, float] | None:
    """Die fünf Scores (0 bis 10) aus ``candidates.rubric``; None, wenn sie fehlen."""
    r = _json(rubric, {}) or {}
    scores = r.get("scores") or {}
    out = {}
    for k in SCORE_KEYS:
        v = scores.get(k)
        if isinstance(v, dict):
            v = v.get("value")
        if v is None:
            return None
        out[k] = float(v)
    return out


def fit_rubric_weights(rows: list[dict[str, Any]], min_n: int = MIN_DECISIONS) -> dict[str, Any] | None:
    """Ridge-Fit ``{weights, n, r2}`` aus Zeilen ``{scores: {...}, verdict, reward}``; unter ``min_n`` ``None``."""
    import numpy as np

    xs, ys = [], []
    for row in rows:
        scores = row.get("scores")
        if not scores or any(k not in scores for k in SCORE_KEYS):
            continue
        y = target_value(row.get("verdict"), row.get("reward"))
        if y is None:
            continue
        xs.append([float(scores[k]) / 10.0 for k in SCORE_KEYS])
        ys.append(float(y))
    n = len(ys)
    if n < min_n:
        return None
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    x_mean, y_mean = x.mean(axis=0), y.mean()
    xc, yc = x - x_mean, y - y_mean
    k = len(SCORE_KEYS)
    beta = np.linalg.solve(xc.T @ xc + RIDGE_LAMBDA * np.eye(k), xc.T @ yc)
    pred = xc @ beta + y_mean
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    raw = np.clip(beta, 0.0, None)
    if raw.sum() <= 0:
        raw = np.ones(k)
    weights = clamp_and_normalize({key: float(v) for key, v in zip(SCORE_KEYS, raw / raw.sum())})
    return {"weights": weights, "n": n, "r2": round(max(-1.0, min(1.0, r2)), 4)}


def clamp_and_normalize(weights: dict[str, float]) -> dict[str, float]:
    """Auf [0,05, 0,5] begrenzen und auf Summe 1 normalisieren: der Rest wird auf die Gewichte verteilt,
    die noch nicht an ihrer Grenze liegen (Water-Filling), damit beide Bedingungen zugleich gelten."""
    w = {k: max(0.0, float(weights.get(k, 0.0))) for k in SCORE_KEYS}
    total = sum(w.values()) or 1.0
    w = {k: v / total for k, v in w.items()}
    for _ in range(20):
        w = {k: max(WEIGHT_MIN, min(WEIGHT_MAX, v)) for k, v in w.items()}
        residual = 1.0 - sum(w.values())
        if abs(residual) < 1e-9:
            break
        free = [k for k, v in w.items() if (v < WEIGHT_MAX - 1e-12 if residual > 0 else v > WEIGHT_MIN + 1e-12)]
        if not free:
            break
        share = residual / len(free)
        for k in free:
            w[k] += share
    return {k: round(v, 4) for k, v in w.items()}


def learning_rows(conn: db.Connection, brand_profile_id: str) -> list[dict[str, Any]]:
    """Kandidaten mit Urteil plus bestem 7d-Reward ihrer Clips, für ``fit_rubric_weights``."""
    rewards = {str(cid): float(r) for cid, r in db.fetch_all(conn, SQL_REWARD_BY_CANDIDATE, (brand_profile_id,)) if r is not None}
    rows = []
    for cid, rubric, verdict in db.fetch_all(conn, SQL_VERDICT_ROWS, (brand_profile_id,)):
        scores = scores_from_rubric(rubric)
        if scores is None:
            continue
        rows.append({"candidate_id": str(cid), "scores": scores, "verdict": verdict, "reward": rewards.get(str(cid))})
    return rows


def update_brand_weights(conn: db.Connection, brand_profile_id: str, now: datetime | None = None) -> dict[str, Any] | None:
    """Fit je Markenprofil, Ergebnis in ``brand_profiles.learned_weights`` plus Audit ``learning.updated``."""
    rows = learning_rows(conn, brand_profile_id)
    fit = fit_rubric_weights(rows)
    if fit is None:
        log.info("learning skipped profile=%s n=%s (unter %s)", brand_profile_id, len(rows), MIN_DECISIONS)
        return None
    now = now or datetime.now(UTC)
    learned = {"weights": fit["weights"], "n": fit["n"], "fitted_at": now.isoformat(), "r2": fit["r2"]}
    db.update(conn, "brand_profiles", {"id": brand_profile_id}, learned_weights=db.jsonb(learned))
    ws = db.fetch_one(conn, SQL_PROFILE_WORKSPACE, (brand_profile_id,))
    if ws is not None:
        db.insert(
            conn, "audit_log",
            workspace_id=str(ws[0]), actor_id=None, actor_type="system", action="learning.updated",
            entity="brand_profile", entity_id=brand_profile_id,
            payload=db.jsonb({"n": fit["n"], "r2": fit["r2"], "weights": fit["weights"]}),
        )  # fmt: skip
    log.info("learning updated profile=%s n=%s r2=%s", brand_profile_id, fit["n"], fit["r2"])
    return learned


# -- Hook-Muster ---------------------------------------------------------------------------------
def _upsert_hook_stat(conn: db.Connection, brand_profile_id: str, pattern: str, shown: int, chosen: int, reward_sum: float, reward_n: int, absolute: bool) -> dict[str, Any]:
    row = db.fetch_one(conn, SQL_HOOK_STAT, (brand_profile_id, pattern))
    now = datetime.now(UTC)
    if row is None:
        values = {"shown": int(shown), "chosen": int(chosen), "reward_sum": float(reward_sum), "reward_n": int(reward_n)}
        db.insert(conn, "hook_pattern_stats", brand_profile_id=brand_profile_id, pattern=pattern, updated_at=now, **values)
        return values
    s0, c0, r0, n0 = row
    if absolute:
        values = {"shown": int(shown), "chosen": int(chosen), "reward_sum": float(reward_sum), "reward_n": int(reward_n)}
    else:
        values = {
            "shown": int(s0 or 0) + int(shown), "chosen": int(c0 or 0) + int(chosen),
            "reward_sum": float(r0 or 0.0) + float(reward_sum), "reward_n": int(n0 or 0) + int(reward_n),
        }  # fmt: skip
    db.update(conn, "hook_pattern_stats", {"brand_profile_id": brand_profile_id, "pattern": pattern}, updated_at=now, **values)
    return values


def update_hook_stats(conn: db.Connection, brand_profile_id: str, pattern: str, shown: int = 0, chosen: int = 0, reward: float | None = None) -> dict[str, Any]:
    """Inkrementell: ``shown`` und ``chosen`` addieren, ``reward`` (falls vorhanden) in Summe und Zähler."""
    if pattern not in HOOK_PATTERNS:
        raise ValueError(f"Unbekanntes Hook-Muster {pattern!r}")
    r_sum = float(reward) if reward is not None else 0.0
    r_n = 1 if reward is not None else 0
    return _upsert_hook_stat(conn, brand_profile_id, pattern, shown, chosen, r_sum, r_n, absolute=False)


def rebuild_hook_stats(conn: db.Connection, brand_profile_id: str) -> dict[str, dict[str, Any]]:
    """Nächtliche Neuberechnung aus ``decision_log`` (shown, chosen) und ``performance_feedback`` (Reward über
    ``clips`` zur höchsten ``hook_versions``-Version). Idempotent, schreibt absolute Werte."""
    totals: dict[str, dict[str, Any]] = {p: {"shown": 0, "chosen": 0, "reward_sum": 0.0, "reward_n": 0} for p in HOOK_PATTERNS}
    for dtype, features, chosen in db.fetch_all(conn, SQL_HOOK_DECISIONS, (brand_profile_id,)):
        feats = _json(features, {}) or {}
        ch = _json(chosen, {}) or {}
        if dtype == "hook_variant_shown":
            for p in feats.get("patterns") or []:
                if p in totals:
                    totals[p]["shown"] += 1
        elif dtype == "hook_selected":
            p = ch.get("pattern")
            if p in totals:
                totals[p]["chosen"] += 1
    pattern_cache: dict[str, str | None] = {}
    for clip_id, reward in db.fetch_all(conn, SQL_HOOK_REWARDS, (brand_profile_id,)):
        cid = str(clip_id)
        if cid not in pattern_cache:
            row = db.fetch_one(conn, SQL_HOOK_PATTERN_OF_CLIP, (cid,))
            pattern_cache[cid] = str(row[0]) if row and row[0] else None
        p = pattern_cache[cid]
        if p in totals and reward is not None:
            totals[p]["reward_sum"] += float(reward)
            totals[p]["reward_n"] += 1
    for p, t in totals.items():
        if any(t.values()):
            _upsert_hook_stat(conn, brand_profile_id, p, t["shown"], t["chosen"], t["reward_sum"], t["reward_n"], absolute=True)
    return totals


def load_hook_stats(conn: db.Connection, brand_profile_id: str) -> list[dict[str, Any]]:
    return [
        {"pattern": p, "shown": int(s or 0), "chosen": int(c or 0), "reward_sum": float(r or 0.0), "reward_n": int(n or 0)}
        for p, s, c, r, n in db.fetch_all(conn, SQL_HOOK_STATS, (brand_profile_id,))
    ]


def thompson_order(stats: list[dict[str, Any]], seed: int | None = None) -> list[str]:
    """Reihenfolge der Hook-Muster per Thompson Sampling: Beta(chosen + 1, shown - chosen + 1) je Muster,
    multipliziert mit dem Reward-Mittel (1,0 ohne Daten, auf 3 gedeckelt). Muster ohne Statistik zählen als
    ungezeigt (reine Exploration). Mit ``seed`` deterministisch."""
    rng = random.Random(seed)
    by_pattern = {str(s.get("pattern")): s for s in stats}
    scored = []
    for p in HOOK_PATTERNS:
        s = by_pattern.get(p, {})
        shown = max(0, int(s.get("shown", 0) or 0))
        chosen = max(0, min(shown, int(s.get("chosen", 0) or 0)))
        sample = rng.betavariate(chosen + 1, shown - chosen + 1)
        n = int(s.get("reward_n", 0) or 0)
        factor = min(REWARD_CAP, float(s.get("reward_sum", 0.0) or 0.0) / n) if n > 0 else 1.0
        scored.append((sample * factor, p))
    scored.sort(key=lambda t: -t[0])
    return [p for _score, p in scored]


def active_brand_profiles(conn: db.Connection) -> list[str]:
    """Markenprofile mit mindestens einem Nutzerurteil."""
    return [str(r[0]) for r in db.fetch_all(conn, SQL_ACTIVE_PROFILES)]


__all__ = [
    "MIN_DECISIONS",
    "REWARD_CAP",
    "RIDGE_LAMBDA",
    "VERDICT_SCORES",
    "WEIGHT_MAX",
    "WEIGHT_MIN",
    "active_brand_profiles",
    "clamp_and_normalize",
    "fit_rubric_weights",
    "learning_rows",
    "load_hook_stats",
    "rebuild_hook_stats",
    "scores_from_rubric",
    "target_value",
    "thompson_order",
    "update_brand_weights",
    "update_hook_stats",
    "verdict_score",
]
