"""Skill 4 - Exit Planner. Sets the stop and target BEFORE entry.

Original: stop at OR midpoint (default) / OR low / price / pct / ATR x K, rounded away from
entry; target 2R (1R, 1.5R, price); refuse stop on the wrong side, target on the wrong side,
risk < 0.05% of price; flat-by time, no overnight hold. Never widen a stop.
India: tick from instrument master, min risk max(0.05%, 3 ticks, 3 x est. cost per unit),
flat by 15:10 IST.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

from ..indicators import round_to_tick


@dataclass
class ExitPlan:
    ok: bool
    direction: int
    entry: float
    stop: float | None = None
    target: float | None = None
    risk_per_unit: float | None = None
    reward_risk: float | None = None
    stop_rule: str = ""
    target_rule: str = ""
    flat_by: str | None = None
    refusals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def plan(entry: float, direction: int = 1, stop_rule: str = "or_mid", target: str = "2R", tick: float = 0.05,
         or_high: float | None = None, or_low: float | None = None, atr: float | None = None, atr_k: float = 1.5,
         stop_price: float | None = None, stop_pct: float | None = None, target_price: float | None = None,
         est_cost_per_unit: float = 0.0, flat_by: str | None = "15:10", entry_time: time | None = None) -> ExitPlan:
    p = ExitPlan(ok=False, direction=direction, entry=entry, stop_rule=stop_rule, target_rule=target, flat_by=flat_by)
    if entry <= 0:
        p.refusals.append("Entry price must be positive.")
        return p
    if flat_by and entry_time and entry_time >= time(*map(int, flat_by.split(":"))):
        p.refusals.append(f"Entry at {entry_time:%H:%M} is at or after the flat-by time {flat_by}.")
    raw = None
    if stop_rule == "or_mid":
        if or_high is None or or_low is None:
            p.refusals.append("Opening-range high/low needed for an OR-midpoint stop.")
        else:
            raw = (or_high + or_low) / 2
            p.notes.append(f"Stop = OR midpoint ({or_high:.2f} + {or_low:.2f}) / 2 = {raw:.3f}")
    elif stop_rule == "or_low":
        if or_low is None or or_high is None:
            p.refusals.append("Opening-range levels needed.")
        else:
            raw = or_low if direction > 0 else or_high
    elif stop_rule == "atr":
        if atr is None or atr != atr:
            p.refusals.append("ATR(14) unavailable (insufficient bars).")
        else:
            raw = entry - direction * atr_k * atr
    elif stop_rule == "price":
        raw = stop_price
    elif stop_rule == "pct":
        raw = entry * (1 - direction * (stop_pct or 0) / 100) if stop_pct else None
    if raw is None and not p.refusals:
        p.refusals.append("A stop is required: no stop could be computed from the chosen rule.")
    if p.refusals:
        return p
    stop = round_to_tick(raw, tick, "down" if direction > 0 else "up")
    if (direction > 0 and stop >= entry) or (direction < 0 and stop <= entry):
        p.refusals.append(f"Stop {stop:.2f} is on the wrong side of the entry {entry:.2f}.")
        return p
    risk = abs(entry - stop)
    min_risk = max(entry * 0.0005, 3 * tick, 3 * est_cost_per_unit)
    if risk < min_risk:
        p.refusals.append(f"Risk {risk:.2f} per unit is below the minimum {min_risk:.2f} "
                          "(0.05% of price, 3 ticks or 3x estimated costs): too tight to survive the spread.")
        return p
    if target.upper().endswith("R"):
        r = float(target[:-1])
        tgt = round_to_tick(entry + direction * r * risk, tick, "nearest")
    else:
        tgt = float(target_price) if target_price is not None else None
        if tgt is None:
            p.refusals.append("Target price required.")
            return p
    if (direction > 0 and tgt <= entry) or (direction < 0 and tgt >= entry):
        p.refusals.append(f"Target {tgt:.2f} is on the wrong side of the entry.")
        return p
    p.ok, p.stop, p.target, p.risk_per_unit = True, stop, tgt, round(risk, 4)
    p.reward_risk = round(abs(tgt - entry) / risk, 2)
    p.notes.append("A stop is a plan, not a guarantee: gaps and fast markets can fill beyond it.")
    return p
