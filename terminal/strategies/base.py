"""Strategy interface.

A strategy turns validated candles into a signal frame with one row per bar. A signal on
bar i is decided on the CLOSE of bar i using bars 0..i only; the backtester fills it at the
open of bar i+1. `tests/test_lookahead.py` checks every registered strategy for this.

Signal frame columns:
    long_entry, short_entry : bool
    stop_long, stop_short   : stop price for an entry on this bar
    target_r                : target as a multiple of risk (R)
    level_long, level_short : the price that would trigger an entry (for WAITING states)
    bias                    : +1 bullish context, -1 bearish, 0 neutral
    exit_long, exit_short   : bool, strategy exit on this bar's close (swing rules)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

REFERENCE = "REFERENCE"  # from the 11-skill Cloud9 / day-trader-skill reference
TERMINAL = "TERMINAL"  # from the master build prompt; not in the reference


@dataclass
class Param:
    name: str
    default: Any
    label: str
    min: float | None = None
    max: float | None = None
    step: float | None = None
    options: list | None = None
    help: str = ""


@dataclass
class StrategyMeta:
    id: str
    name: str
    group: str
    styles: list[str]
    timeframes: list[str]
    default_enabled: bool
    trade_capable: bool
    tested: bool
    needs_volume: bool
    summary: str
    rules: dict[str, str]
    original: list[str] = field(default_factory=list)
    adaptations: list[str] = field(default_factory=list)
    params: list[Param] = field(default_factory=list)
    grid: dict[str, list] = field(default_factory=dict)
    max_hold_bars: int | None = None
    skill_modules: list[int] = field(default_factory=list)


class Strategy:
    meta: StrategyMeta

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.meta.params}

    def merged(self, params: dict | None) -> dict:
        p = self.defaults()
        if params:
            p.update({k: v for k, v in params.items() if k in p})
        return p

    def signals(self, df: pd.DataFrame, params: dict | None, ctx: dict) -> pd.DataFrame:
        raise NotImplementedError

    def tags(self, df: pd.DataFrame) -> pd.Series | None:
        """Watchlist tag (bool per bar) for scan-only setups."""
        return None


def empty_frame(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    return pd.DataFrame({
        "long_entry": np.zeros(n, bool), "short_entry": np.zeros(n, bool),
        "stop_long": np.full(n, np.nan), "stop_short": np.full(n, np.nan),
        "target_r": np.full(n, np.nan),
        "level_long": np.full(n, np.nan), "level_short": np.full(n, np.nan),
        "bias": np.zeros(n, int),
        "exit_long": np.zeros(n, bool), "exit_short": np.zeros(n, bool),
    }, index=df.index)


def bar_close_time(df: pd.DataFrame, tf_minutes: int) -> pd.Series:
    return df["timestamp"] + pd.Timedelta(minutes=tf_minutes)


def window_mask(df: pd.DataFrame, tf_minutes: int, start: str, end: str) -> pd.Series:
    """True where the bar CLOSES inside [start, end] IST (entries are decided at bar close)."""
    close_t = bar_close_time(df, tf_minutes)
    mins = close_t.dt.hour * 60 + close_t.dt.minute
    sh, sm = (int(x) for x in start.split(":"))
    eh, em = (int(x) for x in end.split(":"))
    return (mins >= sh * 60 + sm) & (mins <= eh * 60 + em)


def first_per_day(mask: pd.Series, df: pd.DataFrame) -> pd.Series:
    day = df["timestamp"].dt.date
    c = mask.astype(int).groupby(day).cumsum()
    return mask & (c == 1)
