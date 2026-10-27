"""Event-driven backtester.

Safeguards:
- A signal decided on bar i's close fills at bar i+1's open (plus adverse slippage).
- Stops and targets are checked bar by bar; a bar that touches both counts as the STOP.
- A gap through the stop fills at the open (worse than the stop).
- Intraday trades exit at the flat-by time or the last bar of the session; never overnight.
- Every trade pays the Indian cost model on both legs.
- In-sample / out-of-sample split by time, plus walk-forward evaluation.
Results describe the past on the data supplied. They are not evidence of future profit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import numpy as np
import pandas as pd

from . import costs as costmod
from .data.validation import INTRADAY, TF_MINUTES
from .strategies.base import Strategy
from .timeutil import parse_hhmm


@dataclass
class BTSettings:
    timeframe: str
    session: dict
    initial_capital: float = 100000.0
    sizing: str = "risk_pct"  # risk_pct | fixed_qty | fixed_value
    risk_pct: float = 0.5
    fixed_qty: int = 1
    fixed_value: float = 20000.0
    max_leverage: float = 1.0
    segment: str = "EQ"
    product: str = "INTRADAY"
    lot_size: int = 1
    tick: float = 0.05
    slippage_pct: float = 0.03
    slippage_ticks: int = 1
    max_hold_bars: int | None = None
    oos_fraction: float = 0.3
    allow_short: bool = False
    cost_model: dict | None = None


@dataclass
class Trade:
    direction: int
    entry_ts: pd.Timestamp
    entry_price: float
    stop: float
    target: float
    qty: int
    planned_risk: float
    exit_ts: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    gross_pnl: float = 0.0
    costs: float = 0.0
    net_pnl: float = 0.0
    r_multiple: float = 0.0
    bars_held: int = 0
    sample: str = "IS"


@dataclass
class BTResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict
    metrics_is: dict
    metrics_oos: dict
    skipped: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _size(s: BTSettings, equity: float, entry: float, stop: float) -> int:
    risk_unit = abs(entry - stop)
    if risk_unit <= 0:
        return 0
    lot = max(1, s.lot_size)
    if s.sizing == "fixed_qty":
        units = s.fixed_qty * lot
    elif s.sizing == "fixed_value":
        units = int(s.fixed_value // entry)
    else:
        est_cost_unit = entry * 0.001  # rough cost allowance per unit so costs do not push risk over budget
        units = int((equity * s.risk_pct / 100) // (risk_unit + est_cost_unit))
    units = min(units, int(equity * s.max_leverage // entry))
    return int(units // lot * lot)


def run(df: pd.DataFrame, strategy: Strategy, params: dict | None, s: BTSettings) -> BTResult:
    if df.empty:
        raise ValueError("No candles to test")
    if strategy.meta.trade_capable is False:
        raise ValueError(f"{strategy.meta.name} is a watchlist tag only and cannot be backtested as trades")
    if s.timeframe not in strategy.meta.timeframes:
        raise ValueError(f"{strategy.meta.name} supports {', '.join(strategy.meta.timeframes)}, not {s.timeframe}")
    model = s.cost_model or costmod.load_model()
    df = df.reset_index(drop=True)
    ctx = {"timeframe": s.timeframe, "session": s.session, "tick": s.tick}
    p = strategy.merged(params)
    sig = strategy.signals(df, p, ctx)
    allow_short = s.allow_short and bool(p.get("allow_short", False))
    intraday = s.timeframe in INTRADAY
    flat_by = parse_hhmm(s.session["flat_by"]) if intraday else None
    max_hold = s.max_hold_bars or p.get("max_hold") or strategy.meta.max_hold_bars
    split_idx = int(len(df) * (1 - s.oos_fraction)) if s.oos_fraction > 0 else len(df)
    split_ts = df["timestamp"].iloc[min(split_idx, len(df) - 1)]

    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["timestamp"]
    days = ts.dt.date.to_numpy()
    times = ts.dt.time.to_numpy()
    equity = s.initial_capital
    trades: list[Trade] = []
    eq_curve = np.empty(len(df))
    pos: Trade | None = None
    pending: tuple[int, float, float] | None = None  # direction, stop, target_r
    skipped = {"gap_past_stop": 0, "zero_qty": 0, "after_flat_by": 0, "session_end": 0}

    def close_pos(i: int, price: float, reason: str) -> None:
        nonlocal pos, equity
        assert pos is not None
        side = "sell" if pos.direction > 0 else "buy"
        if reason in ("stop", "gap_stop", "time", "session_end", "signal_exit", "max_hold", "end_of_data"):
            price = costmod.slip(price, side, s.slippage_pct, s.slippage_ticks, s.tick)
        pos.exit_ts, pos.exit_price, pos.exit_reason = ts.iloc[i], price, reason
        pos.gross_pnl = (price - pos.entry_price) * pos.qty * pos.direction
        pos.costs = costmod.round_trip(pos.entry_price, price, pos.qty, pos.direction, s.segment, s.product, model)
        pos.net_pnl = pos.gross_pnl - pos.costs
        pos.r_multiple = pos.net_pnl / pos.planned_risk if pos.planned_risk else 0.0
        equity += pos.net_pnl
        trades.append(pos)
        pos = None

    for i in range(len(df)):
        # 1) fill a pending entry at this bar's open
        if pending is not None and pos is None:
            d, stop, tr = pending
            pending = None
            same_session = (not intraday) or (i > 0 and days[i] == days[i - 1])
            if not same_session:
                skipped["session_end"] += 1
            elif intraday and times[i] >= flat_by:
                skipped["after_flat_by"] += 1
            else:
                fill = costmod.slip(o[i], "buy" if d > 0 else "sell", s.slippage_pct, s.slippage_ticks, s.tick)
                if (d > 0 and fill <= stop) or (d < 0 and fill >= stop):
                    skipped["gap_past_stop"] += 1
                else:
                    qty = _size(s, equity, fill, stop)
                    if qty <= 0:
                        skipped["zero_qty"] += 1
                    else:
                        risk = abs(fill - stop)
                        pos = Trade(d, ts.iloc[i], fill, stop, fill + d * tr * risk, qty, risk * qty,
                                    sample="IS" if ts.iloc[i] < split_ts else "OOS")
        # 2) manage an open position on this bar
        if pos is not None:
            if pos.entry_ts != ts.iloc[i]:
                pos.bars_held += 1
            d = pos.direction
            if intraday and (times[i] >= flat_by or (pos.entry_ts.date() != days[i])):
                close_pos(i, o[i], "time")
            else:
                hit_stop = (l[i] <= pos.stop) if d > 0 else (h[i] >= pos.stop)
                hit_tgt = (h[i] >= pos.target) if d > 0 else (l[i] <= pos.target)
                gap_stop = (o[i] <= pos.stop) if d > 0 else (o[i] >= pos.stop)
                if gap_stop and pos.entry_ts != ts.iloc[i]:
                    close_pos(i, o[i], "gap_stop")
                elif hit_stop:
                    close_pos(i, pos.stop, "stop")  # both touched -> stop (conservative)
                elif hit_tgt:
                    close_pos(i, pos.target, "target")
                elif (d > 0 and sig["exit_long"].iat[i]) or (d < 0 and sig["exit_short"].iat[i]):
                    close_pos(i, c[i], "signal_exit")
                elif max_hold and pos.bars_held >= max_hold:
                    close_pos(i, c[i], "max_hold")
                elif intraday and (i + 1 >= len(df) or days[i + 1] != days[i]):
                    close_pos(i, c[i], "session_end")
        # 3) new signal on this bar's close (only when flat)
        if pos is None and pending is None and i + 1 < len(df):
            if sig["long_entry"].iat[i] and not np.isnan(sig["stop_long"].iat[i]):
                pending = (1, float(sig["stop_long"].iat[i]), float(sig["target_r"].iat[i]))
            elif allow_short and sig["short_entry"].iat[i] and not np.isnan(sig["stop_short"].iat[i]):
                pending = (-1, float(sig["stop_short"].iat[i]), float(sig["target_r"].iat[i]))
        mtm = 0.0
        if pos is not None:
            mtm = (c[i] - pos.entry_price) * pos.qty * pos.direction
        eq_curve[i] = equity + mtm

    if pos is not None:
        close_pos(len(df) - 1, c[-1], "end_of_data")
        eq_curve[-1] = equity

    tdf = pd.DataFrame([asdict(t) for t in trades])
    eq = pd.DataFrame({"timestamp": ts, "equity": eq_curve})
    eq["peak"] = eq["equity"].cummax()
    eq["drawdown"] = eq["equity"] - eq["peak"]
    eq["drawdown_pct"] = eq["drawdown"] / eq["peak"] * 100
    in_mkt = _exposure(tdf, ts)
    notes = [
        "Signals decided on bar close, filled at the next bar's open with adverse slippage.",
        "A bar touching both stop and target is counted as a stop.",
        f"Out-of-sample period starts {split_ts:%Y-%m-%d %H:%M}." if s.oos_fraction > 0 else "No out-of-sample split.",
        "Costs use config/cost_model.json (unverified defaults: check against your broker).",
    ]
    return BTResult(
        trades=tdf, equity=eq,
        metrics=metrics(tdf, eq, s.initial_capital, in_mkt),
        metrics_is=metrics(tdf[tdf["sample"] == "IS"] if len(tdf) else tdf, None, s.initial_capital, None),
        metrics_oos=metrics(tdf[tdf["sample"] == "OOS"] if len(tdf) else tdf, None, s.initial_capital, None),
        skipped=skipped, notes=notes,
    )


def _exposure(tdf: pd.DataFrame, ts: pd.Series) -> float | None:
    if tdf.empty:
        return 0.0
    total = 0
    for _, t in tdf.iterrows():
        total += int(((ts >= t["entry_ts"]) & (ts <= t["exit_ts"])).sum())
    return total / len(ts) * 100


def metrics(tdf: pd.DataFrame, eq: pd.DataFrame | None, capital: float, exposure: float | None) -> dict:
    if tdf is None or tdf.empty:
        return {"trades": 0, "net_pnl": 0.0, "note": "No trades"}
    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] <= 0]
    gross_win = wins["net_pnl"].sum()
    gross_loss = -losses["net_pnl"].sum()
    hold = (tdf["exit_ts"] - tdf["entry_ts"])
    m = {
        "trades": int(len(tdf)),
        "net_pnl": round(float(tdf["net_pnl"].sum()), 2),
        "gross_pnl": round(float(tdf["gross_pnl"].sum()), 2),
        "total_costs": round(float(tdf["costs"].sum()), 2),
        "return_pct": round(float(tdf["net_pnl"].sum() / capital * 100), 2),
        "win_rate_pct": round(len(wins) / len(tdf) * 100, 1),
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else None,
        "expectancy": round(float(tdf["net_pnl"].mean()), 2),
        "expectancy_r": round(float(tdf["r_multiple"].mean()), 3),
        "avg_win": round(float(wins["net_pnl"].mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses["net_pnl"].mean()), 2) if len(losses) else 0.0,
        "avg_hold": str(hold.mean()).split(".")[0],
        "avg_bars_held": round(float(tdf["bars_held"].mean()), 1),
        "exit_reasons": tdf["exit_reason"].value_counts().to_dict(),
    }
    if eq is not None:
        m["max_drawdown"] = round(float(eq["drawdown"].min()), 2)
        m["max_drawdown_pct"] = round(float(eq["drawdown_pct"].min()), 2)
    if exposure is not None:
        m["exposure_pct"] = round(exposure, 1)
    if len(tdf) < 30:
        m["warning"] = f"Only {len(tdf)} trades: too few to draw conclusions."
    return m


def walk_forward(df: pd.DataFrame, strategy: Strategy, base_params: dict | None, s: BTSettings,
                 folds: int = 4, min_train_trades: int = 5) -> pd.DataFrame:
    """Anchored walk-forward: for each fold, pick the grid value with the best in-sample
    expectancy on data BEFORE the fold, then evaluate it on the fold only."""
    grid = strategy.meta.grid or {}
    combos = [dict()]
    for k, vals in grid.items():
        combos = [dict(c, **{k: v}) for c in combos for v in vals]
    df = df.reset_index(drop=True)
    if intraday_tf(s.timeframe):
        keys = df["timestamp"].dt.date
        uniq = keys.drop_duplicates().tolist()
        bounds = np.linspace(0, len(uniq), folds + 2).astype(int)
        cut = [uniq[b] if b < len(uniq) else None for b in bounds]
        idx_of = lambda d: int((keys < d).sum()) if d is not None else len(df)  # noqa: E731
    else:
        bounds = np.linspace(0, len(df), folds + 2).astype(int)
        cut = list(bounds)
        idx_of = lambda b: int(b)  # noqa: E731
    rows = []
    s_eval = BTSettings(**{**asdict(s), "oos_fraction": 0.0})
    for f in range(1, folds + 1):
        tr_end, te_end = idx_of(cut[f]), idx_of(cut[f + 1])
        train, test = df.iloc[:tr_end], df.iloc[:te_end]
        if len(train) < 50 or te_end <= tr_end:
            continue
        best, best_score = None, -np.inf
        for combo in combos:
            params = dict(base_params or {}, **combo)
            r = run(train, strategy, params, s_eval)
            if r.metrics["trades"] >= min_train_trades and r.metrics["expectancy"] > best_score:
                best, best_score = params, r.metrics["expectancy"]
        if best is None:
            best = dict(base_params or {})
        r = run(test, strategy, best, s_eval)
        t = r.trades
        fold_ts = df["timestamp"].iloc[tr_end]
        t = t[t["entry_ts"] >= fold_ts] if len(t) else t
        m = metrics(t, None, s.initial_capital, None)
        rows.append({"fold": f, "test_start": str(fold_ts)[:16], "test_end": str(df["timestamp"].iloc[te_end - 1])[:16],
                     "chosen_params": {k: best.get(k) for k in grid}, "train_expectancy": None if best_score == -np.inf else round(best_score, 2),
                     **{k: m.get(k) for k in ("trades", "net_pnl", "win_rate_pct", "expectancy", "expectancy_r", "profit_factor")}})
    return pd.DataFrame(rows)


def intraday_tf(tf: str) -> bool:
    return TF_MINUTES[tf] < 1440
