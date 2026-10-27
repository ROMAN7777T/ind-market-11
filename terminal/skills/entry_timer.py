"""Skill 3 - Entry Timer. Watches an opening-range or level setup bar by bar.

Only CLOSED bars count. States: NOT OPEN, RANGE FORMING, WAITING, TRIGGERED, EXPIRED,
CLOSED, NO DATA. One trigger per setup per day; a trigger more than one bar old is flagged.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..data.validation import TF_MINUTES, drop_incomplete
from ..timeutil import parse_hhmm


def status(day_bars: pd.DataFrame, timeframe: str, as_of: datetime, session: dict, setup: str = "orb",
           or_minutes: int = 15, level: float | None = None, min_volume_x: float = 0.0) -> dict:
    tf = TF_MINUTES[timeframe]
    t = as_of.time()
    op = parse_hhmm(session["market_open"])
    res: dict = {"setup": setup, "as_of": as_of.strftime("%Y-%m-%d %H:%M"), "timeframe": timeframe}
    if as_of.weekday() >= 5:
        return {**res, "state": "CLOSED", "message": "Market closed (weekend)."}
    if t < op:
        return {**res, "state": "NOT OPEN", "message": f"Market opens at {session['market_open']} IST."}
    bars = drop_incomplete(day_bars[day_bars["timestamp"].dt.date == as_of.date()], timeframe, as_of)
    if bars.empty:
        return {**res, "state": "NO DATA", "message": "No closed bars for this session in the data."}
    mins = (bars["timestamp"].dt.hour * 60 + bars["timestamp"].dt.minute) - (op.hour * 60 + op.minute)
    in_range = mins < or_minutes
    rng = bars[in_range]
    after = bars[~in_range]
    if setup == "orb":
        need = -(-or_minutes // tf)
        if len(after) == 0 and (t.hour * 60 + t.minute) - (op.hour * 60 + op.minute) < or_minutes + tf:
            return {**res, "state": "RANGE FORMING", "message": f"Opening range builds until {or_minutes} minutes after the open."}
        if len(rng) < need:
            return {**res, "state": "NO DATA", "message": f"Opening range incomplete ({len(rng)} of {need} bars): halt or thin trading."}
        lvl = round(float(rng["high"].max()), 2)
        res.update(or_high=lvl, or_low=round(float(rng["low"].min()), 2))
    else:
        if level is None:
            return {**res, "state": "NO DATA", "message": "A level is required for a level setup."}
        lvl = float(level)
        after = bars
    res["level"] = lvl
    avg_rng_vol = float(rng["volume"].mean()) if len(rng) and setup == "orb" else None
    cutoff = parse_hhmm(session["no_entries_after"])
    for i, (_, b) in enumerate(after.iterrows()):
        close_time = (b["timestamp"] + pd.Timedelta(minutes=tf))
        if b["close"] > lvl:
            if min_volume_x and avg_rng_vol and b["volume"] < min_volume_x * avg_rng_vol:
                continue
            if close_time.time() > cutoff:
                break
            age = len(after) - 1 - i
            return {**res, "state": "TRIGGERED", "trigger_time": close_time.strftime("%H:%M"),
                    "trigger_price": round(float(b["close"]), 2), "bar_start": b["timestamp"].strftime("%H:%M"),
                    "pct_over": round((b["close"] / lvl - 1) * 100, 2),
                    "stale": age >= 1, "bars_since": age,
                    "message": f"Bar {b['timestamp']:%H:%M} closed at {b['close']:.2f}, above {lvl:.2f}."
                               + (f" Trigger is {age} bar(s) old: a late entry is a different trade." if age >= 1 else "")}
    if t > cutoff:
        return {**res, "state": "EXPIRED", "message": f"No close above {lvl:.2f} before the {session['no_entries_after']} entry cutoff."}
    last = round(float(bars["close"].iloc[-1]), 2)
    return {**res, "state": "WAITING", "last_close": last, "distance": round(lvl - last, 2),
            "distance_pct": round((last / lvl - 1) * 100, 2),
            "message": f"Last close {last:.2f} is {lvl - last:.2f} below the level {lvl:.2f}."}
