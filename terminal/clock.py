"""The market clock used by the scanner, paper desk and alerts.

Without a verified LIVE provider the terminal runs on a REPLAY clock over stored data, so
paper trades can be stepped forward bar by bar. The replay clock never pretends to be live.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from . import db
from .data import store
from .data.validation import TF_MINUTES
from .timeutil import now_ist, to_ist


def is_live() -> bool:
    from .providers.manager import provider_manager

    return provider_manager().live_data_ok()


def now() -> datetime:
    if is_live():
        return now_ist()
    v = db.get_setting("replay_clock")
    if v:
        return to_ist(datetime.fromisoformat(v))
    return default_replay_time()


def mode_label() -> str:
    return "LIVE CLOCK" if is_live() else "REPLAY CLOCK"


def default_replay_time() -> datetime:
    """10:30 IST on the latest session found in stored data, or now if there is no data."""
    ends = [r["end_ts"] for r in store.list_datasets() if r["end_ts"]]
    if not ends:
        return now_ist()
    last = max(to_ist(datetime.fromisoformat(e)) for e in ends)
    return last.replace(hour=10, minute=30, second=0, microsecond=0)


def set_replay(ts: datetime) -> None:
    db.set_setting("replay_clock", to_ist(ts).isoformat(timespec="seconds"))


def advance(minutes: int) -> datetime:
    t = now() + timedelta(minutes=minutes)
    set_replay(t)
    return t


def bars_until(symbol: str, timeframe: str, as_of: datetime) -> pd.DataFrame:
    """Bars of `symbol` that had CLOSED by `as_of` (bar timestamps are bar starts)."""
    df = store.load(symbol, timeframe)
    if df.empty:
        return df
    if timeframe == "1d":
        d = df["timestamp"].dt.date
        closed_today = as_of.time() >= datetime.strptime(store.session_settings()["market_close"], "%H:%M").time()
        mask = (d < as_of.date()) | ((d == as_of.date()) & closed_today)
        return df[mask].reset_index(drop=True)
    end = df["timestamp"] + pd.Timedelta(minutes=TF_MINUTES[timeframe])
    return df[end <= pd.Timestamp(as_of)].reset_index(drop=True)


def price_at(symbol: str, as_of: datetime) -> dict | None:
    """Latest closed-bar price at `as_of` from the finest stored timeframe."""
    tf = store.finest_timeframe(symbol)
    if tf is None:
        return None
    bars = bars_until(symbol, tf, as_of)
    if bars.empty:
        return None
    last = bars.iloc[-1]
    return {"symbol": symbol, "price": float(last["close"]), "bar_ts": last["timestamp"], "timeframe": tf,
            "mode": (store.symbol_mode(symbol) or "").value if store.symbol_mode(symbol) else None,
            "open": float(last["open"]), "high": float(last["high"]), "low": float(last["low"])}
