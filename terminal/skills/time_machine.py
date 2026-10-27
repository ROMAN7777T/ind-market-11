"""Skill 5 - Time Machine.

Original method: keep FULL past sessions only; turn each 5-minute bar into four ratios to
the previous close; rebuild the rest of today 10,000 times by drawing, for each remaining
bar, a past bar from the same time of day (+/- 2 bars), scaled to the current price; check
the stop first, then the target (a bar touching both = stop). Report target first / stop
first / neither / green, the close distribution and average R; re-run the plan's own rule
on every past session (history); give a verdict vs break-even 1/(1+R). Fixed seed.

India: 75 bars per NSE session (09:15-15:30), `until` = flat-by (15:10), and round-trip
costs are deducted from every replay's R (not in the original).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from ..data.validation import expected_bars_per_session
from ..timeutil import parse_hhmm


def _pool(df5: pd.DataFrame, before: datetime.date, session: dict) -> tuple[np.ndarray, list]:
    need = expected_bars_per_session("5m", session)
    days = df5["timestamp"].dt.date
    sessions = []
    for d, g in df5[days < before].groupby(days[days < before]):
        if len(g) == need:
            sessions.append((d, g.reset_index(drop=True)))
    ratios = []
    for d, g in sessions:
        prev = g["close"].shift(1)
        prev.iloc[0] = g["open"].iloc[0]
        r = np.stack([g["open"] / prev, g["high"] / prev, g["low"] / prev, g["close"] / prev], axis=1)
        ratios.append(r)
    return (np.stack(ratios) if ratios else np.empty((0, need, 4))), sessions


def verdict(target_first: float, stop_first: float, r: float) -> str:
    hit = target_first + stop_first
    if hit <= 0:
        return "No replay reached the stop or the target: the price at the end decides everything."
    share = target_first / hit * 100
    be = 100 / (1 + r)
    diff = share - be
    if abs(diff) < 5:
        return ("Close to a coin flip" if abs(r - 1) < 1e-9 else "Close to break-even") + \
            f": target first in {share:.1f}% of replays that hit a side (break-even {be:.1f}%)."
    side = "target" if diff > 0 else "stop"
    strength = "Strongly toward" if abs(diff) >= 15 else "Leans toward"
    return f"{strength} the {side}: target first in {share:.1f}% of replays that hit a side (break-even {be:.1f}%)."


def run(df5: pd.DataFrame, plan: dict, session: dict, n: int = 10000, seed: int = 19, until: str | None = None,
        cost_per_unit: float = 0.0, min_sessions: int = 20) -> dict:
    """plan: {date, entry_bar_ts (bar START of the entry bar), entry, stop, target, direction, target_r,
    or_minutes, stop_rule}. The entry happens at the close of the entry bar."""
    until = until or session["flat_by"]
    d = pd.Timestamp(plan["entry_bar_ts"]).date()
    pool, sessions = _pool(df5, d, session)
    if len(sessions) < min_sessions:
        return {"ok": False, "message": f"Only {len(sessions)} full past sessions (need {min_sessions}). Import more 5-minute history."}
    op = parse_hhmm(session["market_open"])
    eb = pd.Timestamp(plan["entry_bar_ts"])
    entry_slot = ((eb.hour * 60 + eb.minute) - (op.hour * 60 + op.minute)) // 5
    u = parse_hhmm(until)
    until_slot = ((u.hour * 60 + u.minute) - (op.hour * 60 + op.minute)) // 5  # bars starting before `until`
    slots = list(range(entry_slot + 1, min(until_slot, pool.shape[1])))
    if not slots:
        return {"ok": False, "message": "No bars left between the entry and the end time."}
    entry, stop, target = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    direction = int(plan.get("direction", 1))
    risk = abs(entry - stop)
    if risk <= 0 or (direction > 0 and not (stop < entry < target)) or (direction < 0 and not (target < entry < stop)):
        return {"ok": False, "message": "Plan does not make sense (stop/target on the wrong side)."}
    cost_r = cost_per_unit / risk

    rng = np.random.default_rng(seed)
    price = np.full(n, entry)
    status = np.zeros(n, int)  # 0 open, 1 target, -1 stop
    paths = np.empty((n, len(slots)))
    n_sess, n_slots = pool.shape[0], pool.shape[1]
    for j, k in enumerate(slots):
        src_s = rng.integers(0, n_sess, n)
        src_k = np.clip(k + rng.integers(-2, 3, n), 0, n_slots - 1)
        r = pool[src_s, src_k]  # (n, 4)
        o, h, l, c = (price[:, None] * r).T
        open_ = status == 0
        if direction > 0:
            hit_s = open_ & (l <= stop)
            hit_t = open_ & ~hit_s & (h >= target)
        else:
            hit_s = open_ & (h >= stop)
            hit_t = open_ & ~hit_s & (l <= target)
        status[hit_s], status[hit_t] = -1, 1
        price = np.where(open_, c, price)
        paths[:, j] = price
    final = price
    rr = abs(target - entry) / risk
    R = np.where(status == 1, rr, np.where(status == -1, -1.0, direction * (final - entry) / risk)) - cost_r
    green = (status == 1) | ((status == 0) & (direction * (final - entry) > 0))
    res = {
        "ok": True, "seed": seed, "replays": n, "sessions_in_pool": len(sessions), "bars_replayed": len(slots),
        "until": until,
        "target_first_pct": round((status == 1).mean() * 100, 1),
        "stop_first_pct": round((status == -1).mean() * 100, 1),
        "neither_pct": round((status == 0).mean() * 100, 1),
        "green_pct": round(green.mean() * 100, 1),
        "close_median": round(float(np.median(final)), 2),
        "close_p5": round(float(np.percentile(final, 5)), 2),
        "close_p95": round(float(np.percentile(final, 95)), 2),
        "avg_r": round(float(R.mean()), 3),
        "cost_r": round(cost_r, 3),
        "fan": {q: np.percentile(paths, q, axis=0).round(2).tolist() for q in (5, 25, 50, 75, 95)},
        "final_prices": final,
    }
    res["verdict"] = verdict(res["target_first_pct"], res["stop_first_pct"], rr)
    extra = []
    if res["neither_pct"] > 40:
        extra.append(f"{res['neither_pct']}% of replays hit neither by {until}; the price at {until} decides those.")
    lean_target = "toward the target" in res["verdict"]
    lean_stop = "toward the stop" in res["verdict"]
    if (lean_target and res["avg_r"] < 0) or (lean_stop and res["avg_r"] > 0):
        extra.append(f"Average R is {res['avg_r']:+.3f} after costs, against the lean.")
    res["extra"] = extra
    res["history"] = _history(sessions, plan, session, until, cost_r)
    return res


def _history(sessions: list, plan: dict, session: dict, until: str, cost_r: float) -> dict | None:
    """Re-run an ORB plan's own rule on every pooled session (what really happened)."""
    if plan.get("setup") != "orb":
        return None
    orm = int(plan.get("or_minutes", 15))
    nr = -(-orm // 5)
    tr = float(plan.get("target_r", 2.0))
    rule = plan.get("stop_rule", "or_mid")
    cutoff = parse_hhmm(session["no_entries_after"])
    u = parse_hhmm(until)
    out = {"fired": 0, "target": 0, "stop": 0, "neither": 0, "r": []}
    for _, g in sessions:
        rng_hi, rng_lo = g["high"].iloc[:nr].max(), g["low"].iloc[:nr].min()
        stop = (rng_hi + rng_lo) / 2 if rule == "or_mid" else rng_lo
        for i in range(nr, len(g)):
            ct = (g["timestamp"].iloc[i] + pd.Timedelta(minutes=5)).time()
            if ct > cutoff:
                break
            if g["close"].iloc[i] > rng_hi:
                e = g["close"].iloc[i]
                risk = e - stop
                if risk <= 0:
                    break
                tgt = e + tr * risk
                out["fired"] += 1
                res = None
                last = e
                for j in range(i + 1, len(g)):
                    if g["timestamp"].iloc[j].time() >= u:
                        break
                    if g["low"].iloc[j] <= stop:
                        res = -1.0
                        break
                    if g["high"].iloc[j] >= tgt:
                        res = tr
                        break
                    last = g["close"].iloc[j]
                if res is None:
                    out["neither"] += 1
                    out["r"].append((last - e) / risk - cost_r)
                else:
                    out["target" if res > 0 else "stop"] += 1
                    out["r"].append(res - cost_r)
                break
    out["avg_r"] = round(float(np.mean(out["r"])), 3) if out["r"] else None
    out["sessions"] = len(sessions)
    del out["r"]
    return out
