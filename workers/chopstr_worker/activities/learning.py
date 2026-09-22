"""Activities der Lernschleife (Phase 5b): ``find_learning_profiles`` und ``learn_brand_profile``.

``learn_brand_profile(brand_profile_id)`` ruft ``learning.update_brand_weights`` (Ridge-Fit ab 20 Urteilen,
Ergebnis in ``brand_profiles.learned_weights``, Audit ``learning.updated``) und ``learning.rebuild_hook_stats``
(Hook-Muster-Statistik aus Decision Log und Performance-Feedback, idempotent). Logging nur mit IDs und Zählern.
"""

from __future__ import annotations

import logging
from typing import Any

from temporalio import activity

from .. import learning
from . import common

log = logging.getLogger("chopstr.activities.learning")


def run_learn_brand_profile(ctx: common.Context, brand_profile_id: str) -> dict[str, Any]:
    learned = learning.update_brand_weights(ctx.conn, brand_profile_id)
    totals = learning.rebuild_hook_stats(ctx.conn, brand_profile_id)
    patterns = sum(1 for t in totals.values() if any(t.values()))
    return {
        "brand_profile_id": brand_profile_id,
        "learned": learned is not None,
        "n": int(learned["n"]) if learned else 0,
        "r2": learned["r2"] if learned else None,
        "hook_patterns": patterns,
    }


@activity.defn(name="find_learning_profiles")
def find_learning_profiles() -> list[str]:
    ctx = common.open_context()
    try:
        return learning.active_brand_profiles(ctx.conn)
    finally:
        ctx.close()


@activity.defn(name="learn_brand_profile")
def learn_brand_profile(brand_profile_id: str) -> dict:
    ctx = common.open_context()
    try:
        return run_learn_brand_profile(ctx, brand_profile_id)
    finally:
        ctx.close()


__all__ = ["find_learning_profiles", "learn_brand_profile", "run_learn_brand_profile"]
