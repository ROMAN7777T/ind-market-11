"""SQLite storage with forward-only migrations. Never drops user tables.

Secrets (passwords, OTPs, MPINs, TOTP secrets, session tokens) must never be written here.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from . import config

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS watchlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS watchlist_items (
        watchlist_id INTEGER NOT NULL, symbol TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (watchlist_id, symbol));
    CREATE TABLE IF NOT EXISTS datasets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
        mode TEXT NOT NULL, source TEXT NOT NULL, path TEXT NOT NULL, rows INTEGER NOT NULL,
        start_ts TEXT, end_ts TEXT, imported_at TEXT NOT NULL, quality TEXT,
        UNIQUE (symbol, timeframe));
    CREATE TABLE IF NOT EXISTS instruments (
        symbol TEXT PRIMARY KEY, name TEXT, segment TEXT NOT NULL, exchange TEXT NOT NULL,
        underlying TEXT, expiry TEXT, strike REAL, option_type TEXT,
        tick_size REAL, lot_size INTEGER, source TEXT NOT NULL, as_of TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS holidays (date TEXT PRIMARY KEY, description TEXT, source TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS strategy_settings (
        strategy_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, params TEXT NOT NULL, updated TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS paper_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, initial_capital REAL NOT NULL,
        cash REAL NOT NULL, created TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS paper_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, ts TEXT NOT NULL,
        symbol TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL, order_type TEXT NOT NULL,
        limit_price REAL, stop_price REAL, target_price REAL, status TEXT NOT NULL,
        strategy TEXT, reason TEXT, fill_price REAL, fill_ts TEXT, costs REAL, product TEXT,
        data_mode TEXT, intent TEXT NOT NULL DEFAULT 'entry');
    CREATE TABLE IF NOT EXISTS paper_positions (
        account_id INTEGER NOT NULL, symbol TEXT NOT NULL, qty INTEGER NOT NULL, avg_price REAL NOT NULL,
        stop REAL, target REAL, strategy TEXT, opened_ts TEXT NOT NULL, product TEXT,
        lot_size INTEGER NOT NULL DEFAULT 1, planned_risk REAL NOT NULL DEFAULT 0, entry_costs REAL NOT NULL DEFAULT 0,
        segment TEXT NOT NULL DEFAULT 'EQ', last_checked_ts TEXT, data_mode TEXT,
        PRIMARY KEY (account_id, symbol));
    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, symbol TEXT NOT NULL,
        direction TEXT NOT NULL, qty INTEGER NOT NULL, entry_ts TEXT NOT NULL, entry_price REAL NOT NULL,
        exit_ts TEXT NOT NULL, exit_price REAL NOT NULL, gross_pnl REAL NOT NULL, costs REAL NOT NULL,
        net_pnl REAL NOT NULL, r_multiple REAL, strategy TEXT, exit_reason TEXT, notes TEXT, tags TEXT);
    CREATE TABLE IF NOT EXISTS paper_daily (
        account_id INTEGER NOT NULL, date TEXT NOT NULL, start_equity REAL NOT NULL,
        PRIMARY KEY (account_id, date));
    CREATE TABLE IF NOT EXISTS risk_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT, strategy TEXT,
        decision TEXT NOT NULL, reasons TEXT, details TEXT);
    CREATE TABLE IF NOT EXISTS backtests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL, strategy TEXT NOT NULL,
        timeframe TEXT NOT NULL, params TEXT, settings TEXT, metrics TEXT, data_mode TEXT);
    CREATE TABLE IF NOT EXISTS news (
        id TEXT PRIMARY KEY, headline TEXT NOT NULL, publisher TEXT, url TEXT, published_at TEXT,
        retrieved_at TEXT NOT NULL, symbols TEXT, category TEXT, sentiment TEXT, relevance TEXT,
        source TEXT NOT NULL, verification TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, kind TEXT NOT NULL, level REAL,
        at_time TEXT, date TEXT, active INTEGER NOT NULL DEFAULT 1, rang_at TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS connection_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, provider TEXT NOT NULL,
        event TEXT NOT NULL, detail TEXT);
    CREATE TABLE IF NOT EXISTS earnings (
        symbol TEXT NOT NULL, period_end TEXT NOT NULL, basis TEXT NOT NULL, revenue REAL, ebitda REAL,
        pat REAL, eps REAL, source TEXT NOT NULL, PRIMARY KEY (symbol, period_end, basis));
    CREATE TABLE IF NOT EXISTS option_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT, underlying TEXT NOT NULL, expiry TEXT NOT NULL, as_of TEXT NOT NULL,
        source TEXT NOT NULL, mode TEXT NOT NULL, path TEXT NOT NULL, rows INTEGER NOT NULL,
        UNIQUE (underlying, expiry, as_of));
    CREATE TABLE IF NOT EXISTS insider (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, symbol TEXT NOT NULL, person TEXT,
        category TEXT, txn_type TEXT, qty REAL, value REAL, date TEXT, source TEXT NOT NULL);
    """,
]


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")  # persistent setting, set once
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = row["v"] or 0
        for i, script in enumerate(MIGRATIONS, start=1):
            if i > current:
                conn.executescript(script)
                conn.execute("INSERT INTO schema_version (version) VALUES (?)", (i,))


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_str() -> str:
    from .timeutil import now_ist

    return now_ist().isoformat(timespec="seconds")


_SETTINGS: dict[str, Any] = {}
_MISSING = object()


def get_setting(key: str, default: Any = None) -> Any:
    cache_key = f"{config.db_path()}::{key}"
    if cache_key not in _SETTINGS:
        with session() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        _SETTINGS[cache_key] = json.loads(row["value"]) if row else _MISSING
    v = _SETTINGS[cache_key]
    return default if v is _MISSING else v


def set_setting(key: str, value: Any) -> None:
    from .secure import assert_not_secret

    assert_not_secret(key, value)
    with session() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
    _SETTINGS[f"{config.db_path()}::{key}"] = json.loads(json.dumps(value))


def get_section(name: str, defaults: dict) -> dict:
    stored = get_setting(name, {}) or {}
    merged = dict(defaults)
    merged.update({k: v for k, v in stored.items() if k in defaults})
    return merged


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with session() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with session() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def log_connection(provider: str, event: str, detail: str = "") -> None:
    from .secure import redact

    execute(
        "INSERT INTO connection_log (ts, provider, event, detail) VALUES (?, ?, ?, ?)",
        (now_str(), provider, event, redact(detail)),
    )


def holiday_set() -> tuple[set, bool]:
    from datetime import date

    rs = rows("SELECT date FROM holidays")
    return {date.fromisoformat(r["date"]) for r in rs}, bool(rs)


def iso(ts: datetime) -> str:
    return ts.isoformat(timespec="seconds")
