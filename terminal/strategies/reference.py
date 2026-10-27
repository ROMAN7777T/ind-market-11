"""Strategies derived from the 11-skill reference (Cloud9 Markets / day-trader-skill v2.0.0).

ORB uses the reference's own rules, translated to NSE hours. The five daily setups are
watchlist tags in the reference (skill 1, Chart Scanner) with no exits; the exits here are
PROPOSED Indian-market adaptations, disabled by default until backtested.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..data.validation import TF_MINUTES
from .base import (REFERENCE, Param, Strategy, StrategyMeta, empty_frame, first_per_day, window_mask)


class OpeningRangeBreakout(Strategy):
    meta = StrategyMeta(
        id="REF_ORB",
        name="Opening-Range Breakout (ORB)",
        group=REFERENCE,
        styles=["intraday"],
        timeframes=["5m", "1m"],
        default_enabled=True,
        trade_capable=True,
        tested=False,
        needs_volume=False,
        summary="First completed bar after the opening range that CLOSES above the range high. "
                "Skills 1 (Scanner), 3 (Entry Timer) and 4 (Exit Planner).",
        rules={
            "entry": "First completed bar after the opening range whose close is strictly above the range high "
                     "(a wick or a close equal to the high is not a trigger). One trigger per day.",
            "stop": "Opening-range midpoint (default), range low, or K x ATR(14) below entry; rounded away from entry to the tick.",
            "target": "2R by default (1R / 1.5R configurable).",
            "exit": "Stop, target, or flat-by time (15:10 IST), whichever comes first. No overnight hold.",
            "filters": "Full set of opening-range bars required (a missing bar means a halt or thin stock). "
                       "Entry window 09:30-14:45 IST. Optional trigger-bar volume >= K x average range-bar volume.",
            "invalidation": "No trigger by the entry cutoff = expired. Optional (proposed): a close below the range low "
                            "before the trigger cancels the day's setup.",
            "failure_modes": "False breakouts that reverse into the range; gap days with very wide ranges; "
                             "news/results days; the reference's own test found no edge (NVDA: 24 trades, -$239).",
        },
        original=[
            "15-minute opening range (first three 5-minute bars), range high/low from real highs and lows",
            "Trigger = first completed bar to CLOSE strictly above the range high; one trigger per day",
            "Optional volume filter: trigger-bar volume >= K x range-bar average",
            "Stop at range midpoint (default) / range low / % / ATR(14) x K; rounded away from entry",
            "Target 2R default; refuse risk < 0.05% of price; flat by 15:55 ET; no entries before 09:45 or after 15:30 ET",
            "Long only",
        ],
        adaptations=[
            "NSE session: range 09:15-09:30 IST, entries 09:30-14:45 IST, flat by 15:10 IST (before broker auto square-off)",
            "Tick from instrument master instead of 1 cent",
            "Spot indices have no volume: the volume filter is skipped for them (use index futures)",
            "Minimum risk = max(0.05% of price, 3 ticks)",
            "Optional short mirror (not in reference, off by default)",
            "Optional invalidation on a close below the range low (proposed, off by default)",
        ],
        params=[
            Param("or_minutes", 15, "Opening range (minutes)", 5, 60, 5),
            Param("stop_rule", "or_mid", "Stop rule", options=["or_mid", "or_low", "atr"]),
            Param("atr_k", 1.5, "ATR multiple (atr stop)", 0.5, 5.0, 0.25),
            Param("target_r", 2.0, "Target (R)", 1.0, 5.0, 0.5),
            Param("vol_x", 0.0, "Min trigger volume x range avg (0 = off)", 0.0, 5.0, 0.25),
            Param("invalidate_below_low", False, "Cancel on close below range low (proposed)"),
            Param("allow_short", False, "Also mirror for shorts (not in reference)"),
        ],
        grid={"target_r": [1.0, 1.5, 2.0], "stop_rule": ["or_mid", "or_low"]},
        skill_modules=[1, 3, 4],
    )

    def signals(self, df: pd.DataFrame, params: dict | None, ctx: dict) -> pd.DataFrame:
        p = self.merged(params)
        out = empty_frame(df)
        if df.empty:
            return out
        tf = TF_MINUTES[ctx["timeframe"]]
        sess = ctx["session"]
        tick = ctx.get("tick") or 0.05
        oh, om = (int(x) for x in sess["market_open"].split(":"))
        ts = df["timestamp"]
        day = ts.dt.date
        mins_from_open = (ts.dt.hour * 60 + ts.dt.minute) - (oh * 60 + om)
        in_range = (mins_from_open >= 0) & (mins_from_open < p["or_minutes"])
        n_range = int(np.ceil(p["or_minutes"] / tf))
        g_hi = df["high"].where(in_range).groupby(day)
        or_high = g_hi.transform("max")
        or_low = df["low"].where(in_range).groupby(day).transform("min")
        range_count = in_range.groupby(day).transform("sum")
        range_vol = df["volume"].where(in_range).groupby(day).transform("mean")
        after = mins_from_open >= p["or_minutes"]
        valid_day = range_count >= n_range
        window = window_mask(df, tf, sess["no_entries_before"], sess["no_entries_after"])
        atr = ind.atr(df, 14)

        vol_ok = pd.Series(True, index=df.index)
        has_volume = df["volume"].sum() > 0
        if p["vol_x"] and has_volume:
            vol_ok = df["volume"] >= p["vol_x"] * range_vol

        def side(cond_break: pd.Series, cond_against: pd.Series) -> pd.Series:
            raw = after & valid_day & cond_break
            # one trigger per day: the first close beyond the level, whether or not inside the window
            first = first_per_day(raw, df)
            ok = first & window & vol_ok
            if p["invalidate_below_low"]:
                against = (after & valid_day & cond_against).astype(int).groupby(day).cumsum()
                ok &= against == 0
            return ok

        long_ok = side(df["close"] > or_high, df["close"] < or_low)
        mid = (or_high + or_low) / 2
        if p["stop_rule"] == "or_low":
            stop_l = or_low
        elif p["stop_rule"] == "atr":
            stop_l = df["close"] - p["atr_k"] * atr
        else:
            stop_l = mid
        stop_l = np.floor(stop_l / tick + 1e-9) * tick
        min_risk = np.maximum(df["close"] * 0.0005, 3 * tick)
        long_ok &= (df["close"] - stop_l) >= min_risk
        out["long_entry"] = long_ok.fillna(False).to_numpy()
        out["stop_long"] = stop_l.to_numpy()
        out["level_long"] = or_high.where(after & valid_day).to_numpy()

        if p["allow_short"]:
            short_ok = side(df["close"] < or_low, df["close"] > or_high)
            if p["stop_rule"] == "or_low":
                stop_s = or_high
            elif p["stop_rule"] == "atr":
                stop_s = df["close"] + p["atr_k"] * atr
            else:
                stop_s = mid
            stop_s = np.ceil(stop_s / tick - 1e-9) * tick
            short_ok &= (stop_s - df["close"]) >= min_risk
            out["short_entry"] = short_ok.fillna(False).to_numpy()
            out["stop_short"] = stop_s.to_numpy()
            out["level_short"] = or_low.where(after & valid_day).to_numpy()
        out["target_r"] = p["target_r"]
        known = after & valid_day  # range levels are only known once the range has closed
        out["bias"] = np.where(known & (df["close"] > or_high), 1, np.where(known & (df["close"] < or_low), -1, 0))
        return out


# ---------- daily setups (skill 1 pre-market scan) ----------

def _breakout_20d(df: pd.DataFrame) -> pd.Series:
    prior_max = df["close"].shift(1).rolling(20, min_periods=20).max()
    return df["close"] > prior_max


def _bull_flag(df: pd.DataFrame) -> pd.Series:
    c = df["close"]
    pole = c.shift(5) / c.shift(15) - 1  # the 10 sessions before the last 5
    last5_max = c.rolling(5, min_periods=5).max()
    last5_min = c.rolling(5, min_periods=5).min()
    tight = (last5_max - last5_min) / last5_min <= 0.05  # denominator is a [GAP]: proposed = min close
    return (pole > 0.10) & tight


def _reclaim_ma20(df: pd.DataFrame) -> pd.Series:
    m = ind.sma(df["close"], 20)
    return (df["close"].shift(1) < m.shift(1)) & (df["close"] > m)


def _oversold(df: pd.DataFrame) -> pd.Series:
    return ind.rsi(df["close"], 14) < 30


def _oversold_bounce(df: pd.DataFrame) -> pd.Series:
    r = ind.rsi(df["close"], 14)
    return (r.shift(1) < 30) & (df["close"] > df["close"].shift(1))


_DAILY_ORIGINAL_NOTE = ("Original: a pre-market watchlist tag from the Chart Scanner (skill 1) on daily closes, "
                        "price >= $5 and volume >= 1M; it fed the intraday Entry Timer. No stop, target or exit was defined.")


class _DailySetup(Strategy):
    tag_fn = None

    def tags(self, df: pd.DataFrame) -> pd.Series:
        return type(self).tag_fn(df).fillna(False)


class Breakout20D(_DailySetup):
    tag_fn = staticmethod(_breakout_20d)
    meta = StrategyMeta(
        id="REF_BREAKOUT20", name="20-Day Closing-High Breakout", group=REFERENCE,
        styles=["swing"], timeframes=["1d"], default_enabled=False, trade_capable=True, tested=False,
        needs_volume=False, max_hold_bars=10, skill_modules=[1],
        summary="Daily close above every close of the prior 20 sessions. Exits are PROPOSED.",
        rules={
            "entry": "[ORIGINAL tag] close > all prior 20 closes. [PROPOSED] enter next session open.",
            "stop": "[PROPOSED] entry - K x daily ATR(14) (K = 2).",
            "target": "[PROPOSED] 3R.",
            "exit": "[PROPOSED] daily close below SMA(20), or max 10 sessions.",
            "filters": "Price >= Rs 50 and liquidity (scanner). Delivery product only (overnight gap risk).",
            "invalidation": "[PROPOSED] close back below the breakout level before entry fills.",
            "failure_modes": "Breakouts that fail and reverse; gap-downs through the stop overnight.",
        },
        original=[_DAILY_ORIGINAL_NOTE, "Rule: last close above every close of the 20 sessions before it"],
        adaptations=["All entry/stop/target/exit rules are proposed and untested", "Delivery (CNC) only; overnight gaps apply"],
        params=[Param("atr_k", 2.0, "Stop ATR multiple", 0.5, 5.0, 0.25),
                Param("target_r", 3.0, "Target (R)", 1.0, 6.0, 0.5),
                Param("max_hold", 10, "Max hold (sessions)", 2, 40, 1)],
        grid={"atr_k": [1.5, 2.0, 2.5]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tag = self.tags(df)
        atr = ind.atr(df, 14)
        out["long_entry"] = (tag & atr.notna()).to_numpy()
        out["stop_long"] = (df["close"] - p["atr_k"] * atr).to_numpy()
        out["target_r"] = p["target_r"]
        out["level_long"] = df["close"].rolling(20, min_periods=20).max().to_numpy()
        out["bias"] = np.where(tag, 1, 0)
        out["exit_long"] = (df["close"] < ind.sma(df["close"], 20)).to_numpy()
        return out


class BullFlag(_DailySetup):
    tag_fn = staticmethod(_bull_flag)
    meta = StrategyMeta(
        id="REF_BULLFLAG", name="Bull Flag", group=REFERENCE,
        styles=["swing"], timeframes=["1d"], default_enabled=False, trade_capable=True, tested=False,
        needs_volume=False, max_hold_bars=10, skill_modules=[1],
        summary="Up >10% over 10 sessions, then 5 tight closes (<5% range). Exits are PROPOSED.",
        rules={
            "entry": "[ORIGINAL tag] +10% pole then 5 closes in a 5% range. [PROPOSED] enter when a daily close "
                     "breaks above the flag's highest high, the session after a tag.",
            "stop": "[PROPOSED] lowest low of the 5 flag sessions.",
            "target": "[PROPOSED] 2R.",
            "exit": "[PROPOSED] stop, target, or max 10 sessions.",
            "filters": "Liquidity; delivery product.",
            "invalidation": "[PROPOSED] a close below the flag low before the breakout.",
            "failure_modes": "Flags that resolve downward; the 5% range denominator is not specified in the reference.",
        },
        original=[_DAILY_ORIGINAL_NOTE, "Rule: up more than 10% over the 10 sessions before the last 5, then the last 5 closes inside a 5% range"],
        adaptations=["[GAP] 5% range denominator unspecified; implemented as (max-min)/min of the 5 closes",
                     "Entry, stop, target and exit are proposed and untested"],
        params=[Param("target_r", 2.0, "Target (R)", 1.0, 6.0, 0.5), Param("max_hold", 10, "Max hold (sessions)", 2, 40, 1)],
        grid={"target_r": [1.5, 2.0, 3.0]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tag_prev = self.tags(df).shift(1, fill_value=False)
        flag_high = df["high"].shift(1).rolling(5, min_periods=5).max()
        flag_low = df["low"].shift(1).rolling(5, min_periods=5).min()
        entry = tag_prev & (df["close"] > flag_high)
        out["long_entry"] = entry.fillna(False).to_numpy()
        out["stop_long"] = flag_low.to_numpy()
        out["target_r"] = p["target_r"]
        out["level_long"] = flag_high.where(tag_prev).to_numpy()
        out["bias"] = np.where(self.tags(df) | tag_prev, 1, 0)
        return out


class ReclaimMA20(_DailySetup):
    tag_fn = staticmethod(_reclaim_ma20)
    meta = StrategyMeta(
        id="REF_RECLAIM20", name="Reclaim of 20-Day Average", group=REFERENCE,
        styles=["swing"], timeframes=["1d"], default_enabled=False, trade_capable=True, tested=False,
        needs_volume=False, max_hold_bars=15, skill_modules=[1],
        summary="Previous close below SMA(20), last close above it. Exits are PROPOSED.",
        rules={
            "entry": "[ORIGINAL tag] prior close < SMA20 and close > SMA20. [PROPOSED] enter when the next session "
                     "closes above the reclaim-day high.",
            "stop": "[PROPOSED] reclaim-day low.",
            "target": "[PROPOSED] 2R.",
            "exit": "[PROPOSED] daily close back below SMA(20), or max 15 sessions.",
            "filters": "Liquidity; optional market regime (NIFTY above its SMA50) left to the user.",
            "invalidation": "[PROPOSED] close below SMA(20) before entry.",
            "failure_modes": "Whipsaws in sideways markets.",
        },
        original=[_DAILY_ORIGINAL_NOTE, "Rule: the close before was under its 20-day average, the last close is above it"],
        adaptations=["Entry, stop, target and exit are proposed and untested"],
        params=[Param("target_r", 2.0, "Target (R)", 1.0, 6.0, 0.5), Param("max_hold", 15, "Max hold (sessions)", 2, 40, 1)],
        grid={"target_r": [1.5, 2.0, 3.0]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tag_prev = self.tags(df).shift(1, fill_value=False)
        entry = tag_prev & (df["close"] > df["high"].shift(1))
        out["long_entry"] = entry.fillna(False).to_numpy()
        out["stop_long"] = df["low"].shift(1).to_numpy()
        out["target_r"] = p["target_r"]
        out["level_long"] = df["high"].shift(1).where(tag_prev).to_numpy()
        out["bias"] = np.where(self.tags(df) | tag_prev, 1, 0)
        out["exit_long"] = (df["close"] < ind.sma(df["close"], 20)).to_numpy()
        return out


class Oversold(_DailySetup):
    tag_fn = staticmethod(_oversold)
    meta = StrategyMeta(
        id="REF_OVERSOLD", name="Oversold (RSI 14 < 30)", group=REFERENCE,
        styles=["swing"], timeframes=["1d"], default_enabled=True, trade_capable=False, tested=False,
        needs_volume=False, skill_modules=[1],
        summary="Watchlist tag only: RSI(14, Wilder) below 30. Not a trade on its own.",
        rules={
            "entry": "None. [ORIGINAL] scan tag only. The specification keeps it as the precondition for Oversold Bounce.",
            "stop": "n/a", "target": "n/a", "exit": "n/a",
            "filters": "Liquidity.",
            "invalidation": "RSI back above 30.",
            "failure_modes": "Oversold stocks can stay oversold; this tag alone is not a buy.",
        },
        original=[_DAILY_ORIGINAL_NOTE, "Rule: RSI 14 (Wilder) under 30"],
        adaptations=["Kept tag-only, as in the specification (no trades)"],
    )

    def signals(self, df, params, ctx):
        out = empty_frame(df)
        out["bias"] = np.where(self.tags(df), -1, 0)
        return out


class OversoldBounce(_DailySetup):
    tag_fn = staticmethod(_oversold_bounce)
    meta = StrategyMeta(
        id="REF_OVERSOLD_BOUNCE", name="Oversold Bounce", group=REFERENCE,
        styles=["swing"], timeframes=["1d"], default_enabled=False, trade_capable=True, tested=False,
        needs_volume=False, max_hold_bars=7, skill_modules=[1],
        summary="RSI(14) < 30 yesterday and today closed up. Exits are PROPOSED.",
        rules={
            "entry": "[ORIGINAL tag] RSI14 < 30 yesterday and today's close > yesterday's. [PROPOSED] enter when the "
                     "next session closes above the bounce-day high.",
            "stop": "[PROPOSED] lowest low of the last 5 sessions.",
            "target": "[PROPOSED] 1.5R.",
            "exit": "[PROPOSED] RSI(14) > 50, target, stop or max 7 sessions.",
            "filters": "Liquidity; avoid stocks with negative corporate announcements (news check).",
            "invalidation": "[PROPOSED] a new low below the bounce-day low before entry.",
            "failure_modes": "Catching a falling knife; dead-cat bounces.",
        },
        original=[_DAILY_ORIGINAL_NOTE, "Rule: RSI 14 was under 30 yesterday and today closed up"],
        adaptations=["Entry, stop, target and exit are proposed and untested"],
        params=[Param("target_r", 1.5, "Target (R)", 1.0, 4.0, 0.25), Param("max_hold", 7, "Max hold (sessions)", 2, 20, 1)],
        grid={"target_r": [1.0, 1.5, 2.0]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tag_prev = self.tags(df).shift(1, fill_value=False)
        entry = tag_prev & (df["close"] > df["high"].shift(1))
        out["long_entry"] = entry.fillna(False).to_numpy()
        out["stop_long"] = df["low"].rolling(5, min_periods=5).min().to_numpy()
        out["target_r"] = p["target_r"]
        out["level_long"] = df["high"].shift(1).where(tag_prev).to_numpy()
        out["bias"] = np.where(self.tags(df) | tag_prev, 1, 0)
        out["exit_long"] = (ind.rsi(df["close"], 14) > 50).to_numpy()
        return out
