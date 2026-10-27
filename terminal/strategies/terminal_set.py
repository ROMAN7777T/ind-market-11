"""Strategies requested in the master build prompt. They are NOT part of the 11-skill
reference and are untested research strategies. ORB (item 1 of that list) is shared with
the reference implementation REF_ORB.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..data.validation import INTRADAY, TF_MINUTES
from .base import TERMINAL, Param, Strategy, StrategyMeta, empty_frame, window_mask

_NOTE = "Not in the 11-skill reference: added from the master build prompt. Untested research strategy."


def _round_stop(stop: pd.Series, tick: float, long: bool) -> pd.Series:
    return (np.floor(stop / tick + 1e-9) if long else np.ceil(stop / tick - 1e-9)) * tick


def _intraday_window(df: pd.DataFrame, ctx: dict) -> pd.Series:
    if ctx["timeframe"] not in INTRADAY:
        return pd.Series(True, index=df.index)
    s = ctx["session"]
    return window_mask(df, TF_MINUTES[ctx["timeframe"]], s["no_entries_before"], s["no_entries_after"])


class VWAPBreakoutRetest(Strategy):
    meta = StrategyMeta(
        id="T_VWAP_RETEST", name="VWAP Breakout and Retest", group=TERMINAL,
        styles=["intraday"], timeframes=["5m", "15m"], default_enabled=True, trade_capable=True, tested=False,
        needs_volume=True,
        summary="Price crosses VWAP after holding the other side, then retests VWAP and closes back in the breakout direction.",
        rules={
            "entry": "Long: after at least N closes below session VWAP, a close above VWAP (breakout); within M bars a bar "
                     "whose low comes within tol% of VWAP and closes above it (retest) triggers the entry. Short mirrors (optional).",
            "stop": "Below the lower of the retest low and VWAP, minus 0.25 x ATR(14), rounded to tick.",
            "target": "Target R multiple (default 2R).",
            "exit": "Stop, target or flat-by time.",
            "filters": "Requires traded volume (VWAP is undefined for spot indices: use futures). Entry window applies. One entry per side per day.",
            "invalidation": "A close back on the wrong side of VWAP before the retest, or no retest within M bars.",
            "failure_modes": "Choppy days where price oscillates around VWAP; low-volume stocks with unreliable VWAP.",
        },
        original=[_NOTE], adaptations=["Session-anchored VWAP from 09:15 IST"],
        params=[Param("min_below", 3, "Bars on other side before breakout", 1, 12, 1),
                Param("retest_bars", 6, "Bars allowed for retest", 1, 20, 1),
                Param("tol_pct", 0.10, "Retest tolerance (% of VWAP)", 0.0, 1.0, 0.05),
                Param("target_r", 2.0, "Target (R)", 1.0, 5.0, 0.5),
                Param("allow_short", False, "Allow shorts")],
        grid={"target_r": [1.5, 2.0, 3.0]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        if df.empty or df["volume"].sum() == 0:
            return out
        tick = ctx.get("tick") or 0.05
        vw = ind.vwap(df).to_numpy()
        atr = ind.atr(df, 14).to_numpy()
        c, lo, hi = df["close"].to_numpy(), df["low"].to_numpy(), df["high"].to_numpy()
        days = df["timestamp"].dt.date.to_numpy()
        win = _intraday_window(df, ctx).to_numpy()
        le, se = np.zeros(len(df), bool), np.zeros(len(df), bool)
        sl, ss = np.full(len(df), np.nan), np.full(len(df), np.nan)
        lvl_l, lvl_s, bias = np.full(len(df), np.nan), np.full(len(df), np.nan), np.zeros(len(df), int)
        tol = p["tol_pct"] / 100
        below = above = 0
        brk_l = brk_s = -1
        done_l = done_s = False
        for i in range(len(df)):
            if i == 0 or days[i] != days[i - 1]:
                below = above = 0
                brk_l = brk_s = -1
                done_l = done_s = False
            if np.isnan(vw[i]) or np.isnan(atr[i]):
                continue
            bias[i] = 1 if c[i] > vw[i] else -1
            # long side
            if brk_l >= 0 and not done_l:
                if c[i] < vw[i]:
                    brk_l = -1
                elif i - brk_l > p["retest_bars"]:
                    brk_l = -1
                else:
                    lvl_l[i] = vw[i]
                    if lo[i] <= vw[i] * (1 + tol) and c[i] > vw[i] and win[i]:
                        le[i] = True
                        sl[i] = min(lo[i], vw[i]) - 0.25 * atr[i]
                        done_l = True
            if brk_l < 0 and c[i] > vw[i] and below >= p["min_below"]:
                brk_l = i
            # short side
            if p["allow_short"]:
                if brk_s >= 0 and not done_s:
                    if c[i] > vw[i] or i - brk_s > p["retest_bars"]:
                        brk_s = -1
                    else:
                        lvl_s[i] = vw[i]
                        if hi[i] >= vw[i] * (1 - tol) and c[i] < vw[i] and win[i]:
                            se[i] = True
                            ss[i] = max(hi[i], vw[i]) + 0.25 * atr[i]
                            done_s = True
                if brk_s < 0 and c[i] < vw[i] and above >= p["min_below"]:
                    brk_s = i
            below = below + 1 if c[i] < vw[i] else 0
            above = above + 1 if c[i] > vw[i] else 0
        out["long_entry"], out["short_entry"] = le, se
        out["stop_long"] = _round_stop(pd.Series(sl, index=df.index), tick, True).to_numpy()
        out["stop_short"] = _round_stop(pd.Series(ss, index=df.index), tick, False).to_numpy()
        out["level_long"], out["level_short"], out["bias"] = lvl_l, lvl_s, bias
        out["target_r"] = p["target_r"]
        return out


class EMATrendContinuation(Strategy):
    meta = StrategyMeta(
        id="T_EMA_TREND", name="EMA Trend Continuation", group=TERMINAL,
        styles=["intraday", "swing"], timeframes=["5m", "15m", "1d"], default_enabled=True, trade_capable=True,
        tested=False, needs_volume=False,
        summary="EMA 9 > 20 > 50 with a rising EMA 50; enter on a close above the prior N-bar high.",
        rules={
            "entry": "Long when EMA9 > EMA20 > EMA50, EMA50 higher than 5 bars ago, and the close breaks above the highest "
                     "high of the prior N bars. Short mirrors (optional).",
            "stop": "Lowest low of the last 3 bars or EMA20 - 0.5 x ATR, whichever is lower.",
            "target": "Target R multiple (default 2R).",
            "exit": "Stop, target, flat-by (intraday) or a close below EMA20 (swing).",
            "filters": "Entry window for intraday. Warm-up: 55 bars.",
            "invalidation": "EMA alignment breaks before entry.",
            "failure_modes": "Late-trend exhaustion; whipsaws when EMAs converge.",
        },
        original=[_NOTE], adaptations=[],
        params=[Param("breakout_bars", 10, "Breakout lookback (bars)", 3, 40, 1),
                Param("target_r", 2.0, "Target (R)", 1.0, 5.0, 0.5),
                Param("allow_short", False, "Allow shorts")],
        grid={"breakout_bars": [5, 10, 20]}, max_hold_bars=20,
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tick = ctx.get("tick") or 0.05
        c = df["close"]
        e9, e20, e50 = ind.ema(c, 9), ind.ema(c, 20), ind.ema(c, 50)
        atr = ind.atr(df, 14)
        win = _intraday_window(df, ctx)
        prior_hi = df["high"].shift(1).rolling(p["breakout_bars"], min_periods=p["breakout_bars"]).max()
        prior_lo = df["low"].shift(1).rolling(p["breakout_bars"], min_periods=p["breakout_bars"]).min()
        up = (e9 > e20) & (e20 > e50) & (e50 > e50.shift(5))
        dn = (e9 < e20) & (e20 < e50) & (e50 < e50.shift(5))
        out["long_entry"] = (up & (c > prior_hi) & win).fillna(False).to_numpy()
        out["stop_long"] = _round_stop(np.minimum(df["low"].rolling(3).min(), e20 - 0.5 * atr), tick, True).to_numpy()
        out["level_long"] = prior_hi.where(up).to_numpy()
        if p["allow_short"]:
            out["short_entry"] = (dn & (c < prior_lo) & win).fillna(False).to_numpy()
            out["stop_short"] = _round_stop(np.maximum(df["high"].rolling(3).max(), e20 + 0.5 * atr), tick, False).to_numpy()
            out["level_short"] = prior_lo.where(dn).to_numpy()
        out["bias"] = np.where(up, 1, np.where(dn, -1, 0))
        out["target_r"] = p["target_r"]
        if ctx["timeframe"] == "1d":
            out["exit_long"] = (c < e20).to_numpy()
            out["exit_short"] = (c > e20).to_numpy()
        return out


class TrendPullback(Strategy):
    meta = StrategyMeta(
        id="T_PULLBACK", name="Trend Pullback", group=TERMINAL,
        styles=["intraday", "swing"], timeframes=["15m", "1d"], default_enabled=True, trade_capable=True,
        tested=False, needs_volume=False,
        summary="In an uptrend, price dips to EMA20, RSI cools to 40-55, then a close above the prior bar's high resumes the trend.",
        rules={
            "entry": "EMA20 > EMA50 and close > EMA50; a low touched EMA20 within the last 3 bars; RSI(14) between 40 and 55 "
                     "on the prior bar; the bar closes above the prior bar's high.",
            "stop": "Lowest low of the last 5 bars, rounded to tick.",
            "target": "Target R multiple (default 2R).",
            "exit": "Stop, target, flat-by (intraday) or a close below EMA50 (swing).",
            "filters": "Entry window for intraday; long only.",
            "invalidation": "A close below EMA50 before the trigger.",
            "failure_modes": "Pullbacks that become reversals; low-volatility drift.",
        },
        original=[_NOTE], adaptations=[],
        params=[Param("rsi_low", 40, "RSI lower bound", 20, 60, 1), Param("rsi_high", 55, "RSI upper bound", 40, 80, 1),
                Param("target_r", 2.0, "Target (R)", 1.0, 5.0, 0.5)],
        grid={"target_r": [1.5, 2.0, 3.0]}, max_hold_bars=20,
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tick = ctx.get("tick") or 0.05
        c = df["close"]
        e20, e50 = ind.ema(c, 20), ind.ema(c, 50)
        r = ind.rsi(c, 14)
        trend = (e20 > e50) & (c > e50)
        touched = (df["low"] <= e20).astype(float).rolling(3, min_periods=1).max() > 0
        cooled = r.shift(1).between(p["rsi_low"], p["rsi_high"])
        trigger = c > df["high"].shift(1)
        out["long_entry"] = (trend & touched & cooled & trigger & _intraday_window(df, ctx)).fillna(False).to_numpy()
        out["stop_long"] = _round_stop(df["low"].rolling(5, min_periods=5).min(), tick, True).to_numpy()
        out["level_long"] = df["high"].shift(1).where(trend & touched).to_numpy()
        out["bias"] = np.where(trend, 1, np.where(e20 < e50, -1, 0))
        out["target_r"] = p["target_r"]
        if ctx["timeframe"] == "1d":
            out["exit_long"] = (c < e50).to_numpy()
        return out


class RelativeVolumeBreakout(Strategy):
    meta = StrategyMeta(
        id="T_RVOL_BREAKOUT", name="Relative Volume Breakout", group=TERMINAL,
        styles=["intraday", "swing"], timeframes=["5m", "15m", "1d"], default_enabled=True, trade_capable=True,
        tested=False, needs_volume=True,
        summary="Close above the prior N-bar high on relative volume >= X, closing in the top of its range.",
        rules={
            "entry": "Relative volume (vs the same time-of-day over prior sessions, or the prior 20 days on daily bars) >= X, "
                     "close above the highest high of the prior N bars, and close in the top 25% of the bar. Short mirrors (optional).",
            "stop": "The trigger bar's low (high for shorts), rounded to tick.",
            "target": "Target R multiple (default 2R).",
            "exit": "Stop, target, flat-by (intraday) or max hold (swing).",
            "filters": "Requires traded volume; needs at least 5 prior sessions for the volume baseline.",
            "invalidation": "Close back below the breakout level before entry fills.",
            "failure_modes": "Volume spikes on news that fade; block deals inflating volume.",
        },
        original=[_NOTE], adaptations=["Relative volume is time-of-day matched for intraday bars"],
        params=[Param("rvol_min", 2.0, "Min relative volume", 1.0, 6.0, 0.25),
                Param("breakout_bars", 20, "Breakout lookback (bars)", 5, 60, 1),
                Param("target_r", 2.0, "Target (R)", 1.0, 5.0, 0.5),
                Param("allow_short", False, "Allow shorts")],
        grid={"rvol_min": [1.5, 2.0, 3.0]}, max_hold_bars=10,
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        if df.empty or df["volume"].sum() == 0:
            return out
        tick = ctx.get("tick") or 0.05
        rv = ind.relative_volume(df, 20, ctx["timeframe"] in INTRADAY)
        rng = (df["high"] - df["low"]).replace(0, np.nan)
        pos = (df["close"] - df["low"]) / rng
        n = p["breakout_bars"]
        prior_hi = df["high"].shift(1).rolling(n, min_periods=n).max()
        prior_lo = df["low"].shift(1).rolling(n, min_periods=n).min()
        win = _intraday_window(df, ctx)
        hot = rv >= p["rvol_min"]
        out["long_entry"] = (hot & (df["close"] > prior_hi) & (pos >= 0.75) & win).fillna(False).to_numpy()
        out["stop_long"] = _round_stop(df["low"], tick, True).to_numpy()
        out["level_long"] = prior_hi.to_numpy()
        if p["allow_short"]:
            out["short_entry"] = (hot & (df["close"] < prior_lo) & (pos <= 0.25) & win).fillna(False).to_numpy()
            out["stop_short"] = _round_stop(df["high"], tick, False).to_numpy()
            out["level_short"] = prior_lo.to_numpy()
        out["bias"] = np.where(hot & (df["close"] > df["open"]), 1, np.where(hot & (df["close"] < df["open"]), -1, 0))
        out["target_r"] = p["target_r"]
        return out


class SwingTrendContinuation(Strategy):
    meta = StrategyMeta(
        id="T_SWING_TREND", name="Swing Trend Continuation", group=TERMINAL,
        styles=["swing"], timeframes=["1d"], default_enabled=True, trade_capable=True, tested=False,
        needs_volume=False, max_hold_bars=30,
        summary="Daily uptrend (EMA20 > EMA50, close > EMA50) with a fresh MACD bullish crossover.",
        rules={
            "entry": "Daily EMA20 > EMA50, close > EMA50 and the MACD line crosses above its signal line.",
            "stop": "Entry - K x daily ATR(14) (K = 2).",
            "target": "Target R multiple (default 3R).",
            "exit": "Stop, target, a daily close below EMA50, or max 30 sessions.",
            "filters": "Delivery product; warm-up 60 sessions.",
            "invalidation": "A close below EMA50 before entry.",
            "failure_modes": "Overnight gaps; MACD crossovers in range-bound markets.",
        },
        original=[_NOTE], adaptations=["Delivery (CNC) only; overnight gap risk applies"],
        params=[Param("atr_k", 2.0, "Stop ATR multiple", 0.5, 5.0, 0.25), Param("target_r", 3.0, "Target (R)", 1.0, 6.0, 0.5)],
        grid={"atr_k": [1.5, 2.0, 3.0]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tick = ctx.get("tick") or 0.05
        c = df["close"]
        e20, e50 = ind.ema(c, 20), ind.ema(c, 50)
        m = ind.macd(c)
        cross = (m["macd"] > m["signal"]) & (m["macd"].shift(1) <= m["signal"].shift(1))
        trend = (e20 > e50) & (c > e50)
        atr = ind.atr(df, 14)
        out["long_entry"] = (trend & cross).fillna(False).to_numpy()
        out["stop_long"] = _round_stop(c - p["atr_k"] * atr, tick, True).to_numpy()
        out["bias"] = np.where(trend, 1, np.where(e20 < e50, -1, 0))
        out["target_r"] = p["target_r"]
        out["exit_long"] = (c < e50).to_numpy()
        return out


class MeanReversion(Strategy):
    meta = StrategyMeta(
        id="T_MEAN_REVERSION", name="Mean Reversion (Bollinger)", group=TERMINAL,
        styles=["intraday", "swing"], timeframes=["15m", "1d"], default_enabled=False, trade_capable=True,
        tested=False, needs_volume=False, max_hold_bars=10,
        summary="DISABLED BY DEFAULT until tested. Close back inside the lower Bollinger band after an oversold close.",
        rules={
            "entry": "Prior bar closed below the lower Bollinger band (20, 2) with RSI(14) < 30; this bar closes back above the lower band.",
            "stop": "Entry - 1.5 x ATR(14), rounded to tick.",
            "target": "Target R multiple (default 1.5R); also exits on a close at or above the middle band.",
            "exit": "Stop, target, middle-band close, flat-by (intraday) or max hold.",
            "filters": "Disabled by default. Avoid trending markets (not enforced).",
            "invalidation": "A new low below the signal bar before entry.",
            "failure_modes": "Strong downtrends where bands keep expanding.",
        },
        original=[_NOTE], adaptations=[],
        params=[Param("target_r", 1.5, "Target (R)", 0.5, 4.0, 0.25), Param("atr_k", 1.5, "Stop ATR multiple", 0.5, 4.0, 0.25)],
        grid={"target_r": [1.0, 1.5, 2.0]},
    )

    def signals(self, df, params, ctx):
        p = self.merged(params)
        out = empty_frame(df)
        tick = ctx.get("tick") or 0.05
        c = df["close"]
        bb = ind.bollinger(c)
        r = ind.rsi(c, 14)
        setup = (c.shift(1) < bb["bb_lower"].shift(1)) & (r.shift(1) < 30)
        entry = setup & (c > bb["bb_lower"]) & _intraday_window(df, ctx)
        out["long_entry"] = entry.fillna(False).to_numpy()
        out["stop_long"] = _round_stop(c - p["atr_k"] * ind.atr(df, 14), tick, True).to_numpy()
        out["level_long"] = bb["bb_lower"].where(c < bb["bb_lower"]).to_numpy()
        out["bias"] = np.where(c < bb["bb_lower"], -1, 0)
        out["target_r"] = p["target_r"]
        out["exit_long"] = (c >= bb["bb_mid"]).to_numpy()
        return out
