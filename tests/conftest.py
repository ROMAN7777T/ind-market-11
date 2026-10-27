import os
import sys
from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from terminal.timeutil import IST  # noqa: E402

SESSION = {"pre_open_start": "09:00", "pre_open_end": "09:08", "market_open": "09:15", "market_close": "15:30",
           "no_entries_before": "09:30", "no_entries_after": "14:45", "flat_by": "15:10"}


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own empty data folder and fresh in-process caches. No network, no real credentials."""
    monkeypatch.setenv("TERMINAL_HOME", str(tmp_path))
    for name in ("KOTAK_CONSUMER_KEY", "KOTAK_CONSUMER_SECRET", "KOTAK_MOBILE_NUMBER", "KOTAK_UCC", "KOTAK_MPIN",
                 "KOTAK_PASSWORD", "KOTAK_TOTP_SECRET", "KOTAK_ACCESS_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    from terminal import db
    from terminal.data import store
    from terminal.providers import manager

    db._SETTINGS.clear()
    store._invalidate()
    manager._manager = None
    db.init_db()
    yield tmp_path
    db._SETTINGS.clear()
    store._invalidate()
    manager._manager = None


@pytest.fixture
def no_network(monkeypatch):
    import socket

    def guard(*a, **k):
        raise AssertionError("Network access attempted during a test")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


def make_session(d: date, closes: list[float], highs=None, lows=None, opens=None, volume=1000.0, start="09:15", step=5):
    h, m = map(int, start.split(":"))
    t0 = datetime.combine(d, time(h, m), IST)
    n = len(closes)
    opens = opens or [closes[0]] + closes[:-1]
    highs = highs or [max(o, c) + 0.5 for o, c in zip(opens, closes)]
    lows = lows or [min(o, c) - 0.5 for o, c in zip(opens, closes)]
    return pd.DataFrame({"timestamp": [t0 + timedelta(minutes=step * i) for i in range(n)], "open": opens, "high": highs,
                         "low": lows, "close": closes, "volume": [volume] * n})


def random_intraday(days: int = 30, seed: int = 1, start_price: float = 1000.0) -> pd.DataFrame:
    from terminal.data.simulated import generate_symbol, trading_days

    ds = trading_days(days, date(2026, 10, 23), set())
    return generate_symbol(start_price, 0.015, 0.0, ds, seed, 5000)


@pytest.fixture
def session():
    return dict(SESSION)
