"""Paths and default settings. Everything stays inside the project folder.

Set TERMINAL_HOME to point the app (or the test suite) at another folder.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def home() -> Path:
    return Path(os.environ.get("TERMINAL_HOME", PROJECT_ROOT))


def data_dir() -> Path:
    return home() / "data"


def market_dir() -> Path:
    return data_dir() / "market"


def db_path() -> Path:
    return data_dir() / "terminal.db"


def log_dir() -> Path:
    return home() / "logs"


def export_dir() -> Path:
    return home() / "exports"


def config_dir() -> Path:
    return PROJECT_ROOT / "config"


def ensure_dirs() -> None:
    for d in (data_dir(), market_dir(), log_dir(), export_dir()):
        d.mkdir(parents=True, exist_ok=True)


# Session times are IST. They are defaults stored in settings and can be edited in the app.
DEFAULT_SESSION = {
    "pre_open_start": "09:00",
    "pre_open_end": "09:08",
    "market_open": "09:15",
    "market_close": "15:30",
    "no_entries_before": "09:30",
    "no_entries_after": "14:45",
    "flat_by": "15:10",
}

# Central risk-engine research defaults (configurable, not guarantees of safety).
DEFAULT_RISK = {
    "risk_per_trade_pct": 0.5,
    "max_open_risk_pct": 1.5,
    "max_daily_loss_pct": 1.5,
    "max_positions": 3,
    "max_trades_per_day": 3,
    "min_reward_risk": 1.5,
    "require_stop": True,
    "max_position_pct": 50.0,
    "cash_buffer_pct": 10.0,
    "max_leverage": 1.0,
    "allow_short": False,
    "blocked": [],
    "min_order_value": 1000.0,
    "enforce_entry_window": True,
}

DEFAULT_PAPER = {
    "initial_capital": 100000.0,
    "automation_enabled": False,
    "slippage_pct": 0.03,
    "slippage_ticks": 1,
}

STALE_MULTIPLIER = 2  # a live bar older than 2 x timeframe is stale
