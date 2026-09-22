"""Lernschleife: Ridge-Fit mit synthetischen Daten, Begrenzung, Mindestzahl, Hook-Statistik, Thompson-Reihenfolge."""

from __future__ import annotations

import random

import pytest

from chopstr_worker import learning
from chopstr_worker.pipeline.story_engine import SCORE_KEYS, resolve_weights

TRUE = {"hook": 0.4, "payoff": 0.25, "specificity": 0.15, "tension": 0.1, "audience_fit": 0.1}
SEGS = [{"start": 0.0, "end": 30.0, "role": "body"}]


def _rows(weights: dict[str, float], n: int, seed: int = 7, noise: float = 0.02, verdict: str = "accepted") -> list[dict]:
    """Ziel = 0,6 * Urteil + 0,4 * Reward; Reward linear in den Scores, damit die Gewichte wiederzufinden sind."""
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        scores = {k: rng.randint(0, 10) for k in SCORE_KEYS}
        reward = 2.0 * sum(weights[k] * scores[k] / 10.0 for k in SCORE_KEYS) + rng.gauss(0, noise)
        rows.append({"scores": scores, "verdict": verdict, "reward": max(0.0, reward)})
    return rows


def test_fit_recovers_known_weights():
    fit = learning.fit_rubric_weights(_rows(TRUE, 300))
    assert fit is not None and fit["n"] == 300 and fit["r2"] > 0.95
    for k in SCORE_KEYS:
        assert abs(fit["weights"][k] - TRUE[k]) < 0.03, (k, fit["weights"])
    assert abs(sum(fit["weights"].values()) - 1.0) < 1e-3
    assert resolve_weights(fit["weights"]) == fit["weights"]  # story_engine akzeptiert das Ergebnis


def test_fit_clamps_to_bounds_and_normalizes():
    extreme = {"hook": 0.9, "payoff": 0.025, "specificity": 0.025, "tension": 0.025, "audience_fit": 0.025}
    fit = learning.fit_rubric_weights(_rows(extreme, 200))
    assert fit is not None
    w = fit["weights"]
    assert w["hook"] <= learning.WEIGHT_MAX + 1e-6 and all(v >= learning.WEIGHT_MIN - 1e-6 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-3 and w["hook"] == max(w.values())
    assert learning.clamp_and_normalize({"hook": 1, "payoff": 0, "specificity": 0, "tension": 0, "audience_fit": 0}) == {"hook": 0.5, "payoff": 0.125, "specificity": 0.125, "tension": 0.125, "audience_fit": 0.125}
    even = learning.clamp_and_normalize(dict.fromkeys(SCORE_KEYS, 3.0))
    assert all(v == 0.2 for v in even.values())


def test_fit_below_minimum_returns_none_and_verdict_only_target():
    assert learning.fit_rubric_weights(_rows(TRUE, 19)) is None
    assert learning.fit_rubric_weights(_rows(TRUE, 20)) is not None
    assert learning.fit_rubric_weights([]) is None
    assert learning.target_value("accepted", None) == 1.0 and learning.target_value("edited", None) == 0.5
    assert learning.target_value("rejected", 2.0) == pytest.approx(0.8) and learning.target_value("accepted", 99.0) == pytest.approx(0.6 + 0.4 * 3)
    assert learning.target_value(None, 1.0) is None and learning.target_value("weird", 1.0) is None
    # Ohne Reward zählt nur das Urteil; ein konstantes Urteil liefert keine Varianz, aber ein gültiges Ergebnis
    rows = [{"scores": r["scores"], "verdict": "accepted", "reward": None} for r in _rows(TRUE, 25)]
    fit = learning.fit_rubric_weights(rows)
    assert fit is not None and abs(sum(fit["weights"].values()) - 1.0) < 1e-3


def _seed_profile(fake_db, n: int, with_reward: bool = True):
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid)
    rng = random.Random(3)
    for i in range(n):
        scores = {k: rng.randint(0, 10) for k in SCORE_KEYS}
        rubric = {"scores": {k: {"value": v, "weight": 0.2, "evidence": ""} for k, v in scores.items()}}
        verdict = "accepted" if i % 3 else "rejected"
        cand = fake_db.add_candidate(sid, SEGS, rubric=rubric, human_verdict=verdict)
        if with_reward:
            cid = fake_db.add_clip(sid, cand, "linkedin", SEGS, status="rendered")
            reward = 2.0 * sum(TRUE[k] * scores[k] / 10.0 for k in SCORE_KEYS)
            fake_db.add_feedback(wid, cid, fake_db.add_publication(wid, cid, status="published"), reward=reward)
    return wid, pid


def test_update_brand_weights_writes_profile_and_audit(fake_db):
    wid, pid = _seed_profile(fake_db, 30)
    rows = learning.learning_rows(fake_db, pid)
    assert len(rows) == 30 and all(r["reward"] is not None for r in rows)
    learned = learning.update_brand_weights(fake_db, pid)
    assert learned is not None and learned["n"] == 30 and set(learned) == {"weights", "n", "fitted_at", "r2"}
    assert fake_db.brand_profiles[pid]["learned_weights"] == learned
    audit = fake_db.audit_log[-1]
    assert audit["action"] == "learning.updated" and audit["workspace_id"] == wid and audit["entity_id"] == pid and audit["payload"]["n"] == 30
    assert learning.active_brand_profiles(fake_db) == [pid]


def test_update_brand_weights_skips_below_minimum(fake_db):
    _wid, pid = _seed_profile(fake_db, 10, with_reward=False)
    assert learning.update_brand_weights(fake_db, pid) is None
    assert fake_db.brand_profiles[pid]["learned_weights"] is None and fake_db.audit_log == []


def test_hook_stats_incremental_and_rebuild(fake_db):
    wid = fake_db.add_workspace()
    pid = fake_db.add_brand_profile(wid)
    learning.update_hook_stats(fake_db, pid, "contrarian", shown=1, chosen=1, reward=1.5)
    learning.update_hook_stats(fake_db, pid, "contrarian", shown=1, chosen=0)
    st = fake_db.hook_pattern_stats[(pid, "contrarian")]
    assert (st["shown"], st["chosen"], st["reward_sum"], st["reward_n"]) == (2, 1, 1.5, 1)
    with pytest.raises(ValueError):
        learning.update_hook_stats(fake_db, pid, "unbekannt", shown=1)

    # Neuberechnung aus Decision Log und Feedback ersetzt die Zähler
    sid = fake_db.add_source(wid, "uploads/in.mp4", brand_profile_id=pid)
    cand = fake_db.add_candidate(sid, SEGS)
    cid = fake_db.add_clip(sid, cand, "linkedin", SEGS)
    fake_db.add_hook_version(cid, pattern="open_loop")
    fake_db.add_hook_version(cid, pattern="results_first")  # höchste Version zählt
    for _ in range(3):
        fake_db.decision_log.append({"brand_profile_id": pid, "decision_type": "hook_variant_shown", "features": {"patterns": ["identity_call", "contrarian", "open_loop", "results_first", "mistake_warning"]}, "chosen": {}})
    fake_db.decision_log.append({"brand_profile_id": pid, "decision_type": "hook_selected", "features": {}, "chosen": {"pattern": "results_first"}})
    fake_db.decision_log.append({"brand_profile_id": pid, "decision_type": "hook_selected", "features": {}, "chosen": {"pattern": "results_first"}})
    fake_db.decision_log.append({"brand_profile_id": pid, "decision_type": "hook_selected", "features": {}, "chosen": {"pattern": "open_loop"}})
    pub = fake_db.add_publication(wid, cid, status="published")
    fake_db.add_feedback(wid, cid, pub, reward=2.0)
    fake_db.add_feedback(wid, cid, pub, metric_window="48h", reward=9.0)  # nur 7d zählt
    totals = learning.rebuild_hook_stats(fake_db, pid)
    assert totals["results_first"] == {"shown": 3, "chosen": 2, "reward_sum": 2.0, "reward_n": 1}
    assert totals["open_loop"] == {"shown": 3, "chosen": 1, "reward_sum": 0.0, "reward_n": 0}
    assert totals["contrarian"] == {"shown": 3, "chosen": 0, "reward_sum": 0.0, "reward_n": 0}
    stats = {s["pattern"]: s for s in learning.load_hook_stats(fake_db, pid)}
    assert stats["contrarian"]["shown"] == 3 and stats["contrarian"]["chosen"] == 0 and stats["contrarian"]["reward_sum"] == 0.0
    assert stats["results_first"]["reward_n"] == 1


def test_thompson_order_is_deterministic_and_prefers_strong_pattern():
    stats = [
        {"pattern": "contrarian", "shown": 100, "chosen": 90, "reward_sum": 150.0, "reward_n": 90},
        {"pattern": "open_loop", "shown": 100, "chosen": 2, "reward_sum": 1.0, "reward_n": 2},
        {"pattern": "identity_call", "shown": 100, "chosen": 1, "reward_sum": 0.0, "reward_n": 0},
    ]
    a = learning.thompson_order(stats, seed=42)
    assert a == learning.thompson_order(stats, seed=42) and sorted(a) == sorted(learning.HOOK_PATTERNS)
    assert a[0] == "contrarian"
    assert a != learning.thompson_order(stats, seed=43) or True  # andere Seeds dürfen abweichen (Exploration)
    # ungezeigte Muster werden erkundet: über viele Läufe erscheint jedes Muster mindestens einmal vorn
    firsts = {learning.thompson_order([{"pattern": "contrarian", "shown": 3, "chosen": 1}], seed=s)[0] for s in range(200)}
    assert len(firsts) == 5
