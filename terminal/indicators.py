"""Technical indicators on validated candles.

Every function leaves NaN for its warm-up period and uses only past and current bars,
so a value at bar i never depends on bar i+1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    out = s.ewm(span=n, adjust=False, min_periods=n).mean()
    return out


def wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing, seeded with the simple mean of the first n values."""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    valid = np.where(~np.isnan(vals))[0]
    if len(valid) < n:
        return pd.Series(out, index=s.index)
    start = valid[0]
    if np.isnan(vals[start:start + n]).any():
        return pd.Series(out, index=s.index)
    out[start + n - 1] = vals[start:start + n].mean()
    for i in range(start + n, len(vals)):
        out[i] = (out[i - 1] * (n - 1) + vals[i]) / n
    return pd.Series(out, index=s.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = wilder(d.clip(lower=0), n)
    loss = wilder((-d).clip(lower=0), n)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out[(loss == 0) & gain.notna()] = 100.0
    return out


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + k * sd, "bb_lower": mid - k * sd})


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session-anchored VWAP (resets each trading day). NaN when volume is zero (spot indices)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df["timestamp"].dt.date
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    out = pv / vv.replace(0, np.nan)
    return out


def relative_volume(df: pd.DataFrame, lookback_sessions: int = 20, intraday: bool = True) -> pd.Series:
    """Volume vs the average volume of the same bar-of-day over prior sessions (intraday),
    or vs the prior n-day average (daily). Uses prior data only."""
    if not intraday:
        return df["volume"] / df["volume"].shift(1).rolling(lookback_sessions, min_periods=lookback_sessions).mean()
    ts = df["timestamp"]
    day_codes, days = pd.factorize(ts.dt.date)
    slot_codes, slots = pd.factorize(ts.dt.hour * 60 + ts.dt.minute)
    grid = np.full((len(days), len(slots)), np.nan)
    grid[day_codes, slot_codes] = df["volume"].to_numpy(float)
    prior = pd.DataFrame(grid).shift(1).rolling(lookback_sessions, min_periods=max(5, lookback_sessions // 4)).mean()
    base = prior.to_numpy()[day_codes, slot_codes]
    out = df["volume"].to_numpy(float) / np.where(base == 0, np.nan, base)
    return pd.Series(out, index=df.index)


def support_resistance(df: pd.DataFrame, window: int = 5, max_levels: int = 3, tolerance: float = 0.004) -> dict:
    """Estimate levels from confirmed swing highs/lows (a pivot needs `window` bars on each
    side, so the newest `window` bars can never form one). Nearby pivots are clustered."""
    if len(df) < 2 * window + 1:
        return {"support": [], "resistance": []}
    h, l = df["high"], df["low"]
    roll_h = h.rolling(2 * window + 1, center=True).max()
    roll_l = l.rolling(2 * window + 1, center=True).min()
    piv_h = h[(h == roll_h)].dropna()
    piv_l = l[(l == roll_l)].dropna()
    last = float(df["close"].iloc[-1])

    def cluster(levels: pd.Series) -> list[float]:
        out: list[list[float]] = []
        for v in sorted(levels.tolist()):
            if out and abs(v - np.mean(out[-1])) / v <= tolerance:
                out[-1].append(v)
            else:
                out.append([v])
        return [float(np.mean(c)) for c in out if c]

    levels = cluster(pd.concat([piv_h, piv_l]))
    res = sorted([x for x in levels if x > last])[:max_levels]
    sup = sorted([x for x in levels if x < last], reverse=True)[:max_levels]
    return {"support": sup, "resistance": res}


def trend_state(close: pd.Series, fast: int = 20, slow: int = 50) -> str:
    if close.notna().sum() < slow + 5:
        return "INSUFFICIENT DATA"
    f, s = ema(close, fast), ema(close, slow)
    slope = f.iloc[-1] - f.iloc[-6]
    if f.iloc[-1] > s.iloc[-1] and slope > 0 and close.iloc[-1] > f.iloc[-1]:
        return "UPTREND"
    if f.iloc[-1] < s.iloc[-1] and slope < 0 and close.iloc[-1] < f.iloc[-1]:
        return "DOWNTREND"
    return "SIDEWAYS"


def volatility_state(df: pd.DataFrame, n: int = 14, lookback: int = 100) -> str:
    a = atr(df, n) / df["close"]
    if a.notna().sum() < lookback // 2:
        return "INSUFFICIENT DATA"
    hist = a.dropna().iloc[-lookback:]
    pct = (hist < hist.iloc[-1]).mean()
    if pct >= 0.8:
        return "HIGH"
    if pct <= 0.2:
        return "LOW"
    return "NORMAL"


def add_all(df: pd.DataFrame, intraday: bool) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    out["sma20"], out["sma50"], out["sma200"] = sma(c, 20), sma(c, 50), sma(c, 200)
    out["ema9"], out["ema20"], out["ema50"] = ema(c, 9), ema(c, 20), ema(c, 50)
    out["rsi14"] = rsi(c, 14)
    out["atr14"] = atr(out, 14)
    out = out.join(macd(c)).join(bollinger(c))
    if intraday:
        out["vwap"] = vwap(out)
    out["rvol"] = relative_volume(out, 20, intraday)
    return out


def round_to_tick(price: float, tick: float, direction: str = "nearest") -> float:
    """Round to the instrument tick. direction: 'down', 'up' or 'nearest'."""
    if not tick or tick <= 0:
        raise ValueError("A positive tick size is required")
    q = price / tick
    if direction == "down":
        q = np.floor(q + 1e-9)
    elif direction == "up":
        q = np.ceil(q - 1e-9)
    else:
        q = np.floor(q + 0.5)
    decimals = max(0, -int(np.floor(np.log10(tick))) + 1)
    return round(float(q * tick), decimals)
