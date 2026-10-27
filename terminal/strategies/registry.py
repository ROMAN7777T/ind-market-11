"""All strategies, with per-user enabled flags and parameters stored in SQLite."""
from __future__ import annotations

import json

from .. import db
from .base import Strategy
from .reference import Breakout20D, BullFlag, OpeningRangeBreakout, Oversold, OversoldBounce, ReclaimMA20
from .terminal_set import (EMATrendContinuation, MeanReversion, RelativeVolumeBreakout, SwingTrendContinuation,
                           TrendPullback, VWAPBreakoutRetest)

_ALL: list[Strategy] = [
    OpeningRangeBreakout(), Breakout20D(), BullFlag(), ReclaimMA20(), Oversold(), OversoldBounce(),
    VWAPBreakoutRetest(), EMATrendContinuation(), TrendPullback(), RelativeVolumeBreakout(),
    SwingTrendContinuation(), MeanReversion(),
]
BY_ID = {s.meta.id: s for s in _ALL}


def all_strategies() -> list[Strategy]:
    return list(_ALL)


def get(strategy_id: str) -> Strategy:
    return BY_ID[strategy_id]


def settings(strategy_id: str) -> dict:
    s = get(strategy_id)
    rs = db.rows("SELECT enabled, params FROM strategy_settings WHERE strategy_id = ?", (strategy_id,))
    if not rs:
        return {"enabled": s.meta.default_enabled, "params": s.defaults()}
    return {"enabled": bool(rs[0]["enabled"]), "params": s.merged(json.loads(rs[0]["params"]))}


def save(strategy_id: str, enabled: bool, params: dict) -> None:
    s = get(strategy_id)
    db.execute(
        """INSERT INTO strategy_settings (strategy_id, enabled, params, updated) VALUES (?, ?, ?, ?)
           ON CONFLICT(strategy_id) DO UPDATE SET enabled=excluded.enabled, params=excluded.params, updated=excluded.updated""",
        (strategy_id, int(enabled), json.dumps(s.merged(params)), db.now_str()),
    )


def enabled() -> list[Strategy]:
    return [s for s in _ALL if settings(s.meta.id)["enabled"]]
