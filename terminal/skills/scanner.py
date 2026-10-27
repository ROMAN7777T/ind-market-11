"""Skill 1 - Chart Scanner. Lists charts that MATCHED A RULE - not buys, not predictions.

Runs every enabled strategy on the bars that had closed by the clock time. Without a
verified LIVE provider every setup is labelled with its data mode and is not a live signal.
A missing price, invalid candle or stale live feed prevents a fresh signal.

Quality score (0-100), documented in docs/strategy_specification.md section 18:
    data quality  0-25  25 x (1 - missing-bar share of the latest session); 0 if stale
    trend         0-25  25 if the signal agrees with the higher-timeframe trend, 12 if sideways, 0 if opposed
    volume        0-25  25 x clip((relative volume - 0.5) / 1.5, 0, 1); 0 when volume is unavailable
    reward:risk   0-25  25 x min(R / 3, 1)
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from .. import clock
from .. import indicators as ind
from ..config import STALE_MULTIPLIER
from ..data import instruments, store
from ..data.validation import INTRADAY, TF_MINUTES, expected_bars_per_session, is_stale
from ..strategies import registry
from ..strategies.base import Strategy


def _quality(df: pd.DataFrame, tf: str, direction: int, rr: float | None, daily: pd.DataFrame, stale: bool,
             session: dict, has_volume: bool) -> tuple[int, dict]:
    parts = {}
    if stale:
        parts["data"] = 0
    elif tf in INTRADAY:
        last_day = df[df["timestamp"].dt.date == df["timestamp"].dt.date.iloc[-1]]
        exp_so_far = max(1, len(last_day))
        first = last_day["timestamp"].iloc[0]
        span = (last_day["timestamp"].iloc[-1] - first).total_seconds() / 60 / TF_MINUTES[tf] + 1
        missing = max(0.0, span - exp_so_far) / max(span, 1)
        parts["data"] = round(25 * (1 - missing))
    else:
        parts["data"] = 25
    ctx_df = daily if tf in INTRADAY else df
    trend = ind.trend_state(ctx_df["close"]) if len(ctx_df) else "INSUFFICIENT DATA"
    want = "UPTREND" if direction > 0 else "DOWNTREND"
    parts["trend"] = 25 if trend == want else (12 if trend in ("SIDEWAYS", "INSUFFICIENT DATA") else 0)
    if has_volume:
        rv = ind.relative_volume(df, 20, tf in INTRADAY).iloc[-1]
        parts["volume"] = 0 if pd.isna(rv) else round(25 * float(np.clip((rv - 0.5) / 1.5, 0, 1)))
    else:
        parts["volume"] = 0
    parts["reward_risk"] = round(25 * min((rr or 0) / 3, 1))
    parts["higher_tf_trend"] = trend
    return int(parts["data"] + parts["trend"] + parts["volume"] + parts["reward_risk"]), parts


def _snapshot(bars: pd.DataFrame, intraday: bool) -> dict:
    tail = bars.tail(300).reset_index(drop=True)
    c = tail["close"]
    vals = {"ema20": ind.ema(c, 20).iloc[-1], "ema50": ind.ema(c, 50).iloc[-1], "rsi14": ind.rsi(c, 14).iloc[-1],
            "atr14": ind.atr(tail, 14).iloc[-1]}
    if intraday and tail["volume"].sum() > 0:
        vals["vwap"] = ind.vwap(tail).iloc[-1]
    if tail["volume"].sum() > 0:
        vals["rvol"] = ind.relative_volume(tail, 20, intraday).iloc[-1]
    return {k: (None if pd.isna(v) else round(float(v), 2)) for k, v in vals.items()}


def scan_symbol(symbol: str, strategy: Strategy, params: dict, timeframe: str, as_of: datetime, session: dict,
                live: bool) -> dict | None:
    bars = clock.bars_until(symbol, timeframe, as_of)
    if timeframe in INTRADAY:
        bars = bars.tail(expected_bars_per_session(timeframe, session) * 40).reset_index(drop=True)
    mode = store.symbol_mode(symbol)
    base = {"instrument": symbol, "strategy": strategy.meta.name, "strategy_id": strategy.meta.id,
            "group": strategy.meta.group, "timeframe": timeframe,
            "data_mode": mode.value if mode else "NO DATA"}
    min_bars = 60 if timeframe in INTRADAY else 30
    if len(bars) < min_bars:
        return {**base, "classification": "NO-TRADE", "status": "INSUFFICIENT DATA",
                "entry_trigger": f"Needs at least {min_bars} closed bars; has {len(bars)}.", "quality": 0}
    has_volume = bars["volume"].tail(200).sum() > 0
    if strategy.meta.needs_volume and not has_volume:
        return {**base, "classification": "NO-TRADE", "status": "NO VOLUME",
                "entry_trigger": "This strategy needs traded volume (spot indices have none: use futures).", "quality": 0}
    last_ts = bars["timestamp"].iloc[-1]
    stale = live and is_stale(last_ts.to_pydatetime(), timeframe, as_of, STALE_MULTIPLIER)
    status = "STALE FEED - NO SIGNAL" if stale else ("LIVE" if live else f"{base['data_mode']} - NOT A LIVE SIGNAL")
    inst = instruments.get(symbol)
    tick = float(inst["tick_size"]) if inst and inst["tick_size"] else 0.05
    ctx = {"timeframe": timeframe, "session": session, "tick": tick}
    sig = strategy.signals(bars, params, ctx)
    row = sig.iloc[-1]
    last = bars.iloc[-1]
    close = float(last["close"])
    daily = clock.bars_until(symbol, "1d", as_of) if timeframe in INTRADAY else bars
    tagged = None
    if strategy.tags(bars) is not None:
        tagged = bool(strategy.tags(bars).iloc[-1])
    rules = strategy.meta.rules
    out = {**base, "status": status, "data_timestamp": f"{last_ts:%Y-%m-%d %H:%M} IST (bar start)",
           "stop_method": rules["stop"], "target_method": rules["target"], "invalidation": rules["invalidation"],
           "failure_reasons": rules["failure_modes"], "last_close": close}
    out["indicators"] = _snapshot(bars, timeframe in INTRADAY)
    direction = 0
    if row["long_entry"] and not stale:
        direction = 1
    elif row["short_entry"] and not stale:
        direction = -1
    if direction:
        stop = float(row["stop_long"] if direction > 0 else row["stop_short"])
        risk = abs(close - stop)
        tr = float(row["target_r"])
        target = close + direction * tr * risk
        out.update(classification="BULLISH" if direction > 0 else "BEARISH", setup_state="TRIGGERED",
                   entry_trigger=f"Bar closed at {close:.2f} ({last_ts:%d %b}{'' if timeframe == '1d' else f' {last_ts:%H:%M} bar'}) - rule condition met",
                   entry_ref=round(close, 2), stop=round(stop, 2), target=round(target, 2), reward_risk=tr,
                   direction=direction)
        q, parts = _quality(bars, timeframe, direction, tr, daily, stale, session, has_volume)
        out.update(quality=q, quality_parts=parts)
    else:
        lvl_l, lvl_s = row["level_long"], row["level_short"]
        earlier = None
        if timeframe in INTRADAY:
            today = bars["timestamp"].dt.date == last_ts.date()
            fired = sig[today & (sig["long_entry"] | sig["short_entry"])]
            if len(fired):
                earlier = fired.index[-1]
        if earlier is not None:
            b = bars.loc[earlier]
            age = len(bars) - 1 - earlier
            d = 1 if sig.at[earlier, "long_entry"] else -1
            out.update(classification="BULLISH" if d > 0 else "BEARISH", setup_state="TRIGGERED EARLIER",
                       entry_trigger=f"Triggered on the {b['timestamp']:%H:%M} bar at {b['close']:.2f}, {age} bar(s) ago. "
                                     "A late entry is a different trade: no fresh entry is offered.")
        elif not np.isnan(lvl_l) and row["bias"] >= 0 and strategy.meta.trade_capable:
            out.update(classification="NEUTRAL", setup_state="WAITING",
                       entry_trigger=f"Close above {lvl_l:.2f} ({(lvl_l / close - 1) * 100:+.2f}% from {close:.2f})")
        elif not np.isnan(lvl_s) and row["bias"] < 0:
            out.update(classification="NEUTRAL", setup_state="WAITING",
                       entry_trigger=f"Close below {lvl_s:.2f} ({(lvl_s / close - 1) * 100:+.2f}%)")
        else:
            cls = {1: "BULLISH", -1: "BEARISH"}.get(int(row["bias"]), "NO-TRADE")
            out.update(classification=cls if tagged or strategy.meta.trade_capable is False else "NO-TRADE",
                       setup_state="TAGGED" if tagged else "NO SETUP",
                       entry_trigger="Watchlist tag matched (not a trade)" if tagged else "No setup on the latest bar")
        if stale:
            out["classification"] = "NO-TRADE"
        out["quality"] = None
        if not strategy.meta.trade_capable and not tagged:
            return None
    return out


def run(symbols: list[str] | None = None, strategy_ids: list[str] | None = None, as_of: datetime | None = None,
        include_idle: bool = False) -> pd.DataFrame:
    as_of = as_of or clock.now()
    session = store.session_settings()
    live = clock.is_live()
    symbols = symbols or store.symbols()
    strategies = [registry.get(i) for i in strategy_ids] if strategy_ids else registry.enabled()
    rows = []
    for s in strategies:
        cfg = registry.settings(s.meta.id)
        for sym in symbols:
            avail = store.timeframes_for(sym)
            tf = next((t for t in s.meta.timeframes if t in avail), None)
            if tf is None:
                continue
            r = scan_symbol(sym, s, cfg["params"], tf, as_of, session, live)
            if r is None:
                continue
            if not include_idle and r.get("setup_state") in ("NO SETUP", None) and r.get("status") not in ("INSUFFICIENT DATA",):
                continue
            rows.append(r)
    df = pd.DataFrame(rows)
    if not df.empty:
        order = {"TRIGGERED": 0, "TRIGGERED EARLIER": 1, "WAITING": 2, "TAGGED": 3}
        df["_o"] = df.get("setup_state", pd.Series(dtype=str)).map(order).fillna(9)
        df = df.sort_values(["_o", "quality"], ascending=[True, False], na_position="last").drop(columns="_o")
    return df.reset_index(drop=True)


def daily_tags(symbols: list[str] | None = None, as_of: datetime | None = None) -> pd.DataFrame:
    """The reference's pre-market daily scan (skill 1): five tags on daily closes."""
    from ..strategies.reference import Breakout20D, BullFlag, Oversold, OversoldBounce, ReclaimMA20

    as_of = as_of or clock.now()
    rows = []
    for sym in symbols or store.symbols():
        d = clock.bars_until(sym, "1d", as_of)
        if len(d) < 25:
            continue
        rec = {"symbol": sym, "last_close": float(d["close"].iloc[-1]), "as_of": f"{d['timestamp'].iloc[-1]:%Y-%m-%d}",
               "data_mode": store.symbol_mode(sym).value}
        for cls, name in ((Breakout20D, "breakout_20d"), (BullFlag, "bull_flag"), (ReclaimMA20, "reclaim_ma20"),
                          (Oversold, "oversold"), (OversoldBounce, "oversold_bounce")):
            rec[name] = bool(cls().tags(d).iloc[-1])
        rec["traded_value_cr"] = round(float(d["close"].iloc[-1] * d["volume"].iloc[-1]) / 1e7, 2) if d["volume"].iloc[-1] else None
        rows.append(rec)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("traded_value_cr", ascending=False, na_position="last")
    return df
