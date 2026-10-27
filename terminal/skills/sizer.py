"""Skill 6 - Position Sizer.

Original: whole shares = min(max-loss / risk-per-share, position cap, max order, cash after
buffer); size at the HIGHER of plan entry and a fresh price; a stop too far for the max
loss is a refusal, not a smaller order.
India: whole lots for F&O (refuse if one lot exceeds the risk budget), a leverage limit, an
optional broker-margin limit, and estimated round-trip costs included in the max loss.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import costs as costmod


@dataclass
class SizeResult:
    ok: bool
    qty: int = 0
    lots: int = 0
    deciding_limit: str = ""
    limits: dict = field(default_factory=dict)
    sized_at: float = 0.0
    max_loss: float = 0.0
    est_costs: float = 0.0
    notional: float = 0.0
    refusals: list[str] = field(default_factory=list)


def size(entry: float, stop: float, equity: float, cash: float, risk: dict, direction: int = 1, lot_size: int = 1,
         segment: str = "EQ", product: str = "INTRADAY", fresh_price: float | None = None,
         margin_per_unit: float | None = None, target: float | None = None) -> SizeResult:
    r = SizeResult(ok=False)
    lot = max(1, int(lot_size or 1))
    px = entry
    if fresh_price is not None:
        px = max(entry, fresh_price) if direction > 0 else min(entry, fresh_price)
    r.sized_at = px
    risk_unit = (px - stop) * direction
    if risk_unit <= 0:
        r.refusals.append("The stop is not on the protective side of the entry (the price may have moved through it).")
        return r
    if target is not None:
        reward = (target - px) * direction
        if reward <= 0:
            r.refusals.append("Target is not beyond the entry: the move already happened.")
            return r
        if reward / risk_unit < risk["min_reward_risk"]:
            r.refusals.append(f"Reward:risk {reward / risk_unit:.2f} is below the minimum {risk['min_reward_risk']}.")
            return r
    budget = equity * risk["risk_per_trade_pct"] / 100
    cost_unit = costmod.round_trip(px, stop, lot, direction, segment, product) / lot
    usable = max(0.0, cash - equity * risk["cash_buffer_pct"] / 100)
    limits = {
        "max loss": budget / (risk_unit + cost_unit),
        "position cap": equity * risk["max_position_pct"] / 100 / px,
        "leverage": equity * risk["max_leverage"] / px,
    }
    if direction > 0 and segment in ("EQ", "OPT"):
        limits["cash after buffer"] = usable / px  # cash purchases; futures and shorts are bounded by margin/leverage
    if margin_per_unit:
        limits["margin"] = usable / margin_per_unit
    shares = {k: int(math.floor(v / lot)) * lot for k, v in limits.items()}
    r.limits = {k: {"units": v, "lots": v // lot} for k, v in shares.items()}
    r.deciding_limit = min(shares, key=shares.get)
    qty = shares[r.deciding_limit]
    if qty <= 0:
        if r.deciding_limit == "max loss":
            r.refusals.append(f"One {'lot' if lot > 1 else 'unit'} risks {(risk_unit + cost_unit) * lot:,.2f}, "
                              f"more than the {budget:,.2f} max loss per trade. Refused (not shrunk).")
        else:
            r.refusals.append(f"Zero quantity: bound by the {r.deciding_limit} limit.")
        return r
    r.qty, r.lots = qty, qty // lot
    r.notional = qty * px
    if r.notional < risk.get("min_order_value", 0):
        r.refusals.append(f"Order value {r.notional:,.0f} is below the minimum {risk['min_order_value']:,.0f}.")
        return r
    r.est_costs = costmod.round_trip(px, stop, qty, direction, segment, product)
    r.max_loss = round(qty * risk_unit + r.est_costs, 2)
    r.ok = True
    return r
