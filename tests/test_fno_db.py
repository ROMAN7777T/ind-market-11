import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from terminal import db, fno
from terminal.data import store
from terminal.data.modes import DataMode
from terminal.timeutil import IST
from tests.conftest import make_session


def test_put_call_parity():
    S, K, T, r, s = 24000, 24100, 7 / 365, 0.065, 0.14
    c, p = fno.bs_price(S, K, T, r, s, "CE"), fno.bs_price(S, K, T, r, s, "PE")
    assert c - p == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)


def test_implied_vol_round_trip_and_bounds():
    px = fno.bs_price(24000, 24000, 0.05, 0.065, 0.18, "CE")
    assert fno.implied_vol(px, 24000, 24000, 0.05, 0.065, "CE") == pytest.approx(0.18, abs=1e-4)
    assert fno.implied_vol(0.01, 24000, 20000, 0.05, 0.065, "CE") is None  # below intrinsic


def test_greeks_not_computed_without_inputs():
    chain = pd.DataFrame({"strike": [24000.0], "option_type": ["CE"], "ltp": [np.nan], "bid": [np.nan], "ask": [np.nan],
                          "oi": [1.0], "oi_change": [0], "volume": [1], "iv": [np.nan]})
    out = fno.enrich(chain, None, date(2026, 10, 30), datetime(2026, 10, 20, 10, tzinfo=IST), 0.065)
    assert out["delta"].isna().all() and out["iv_source"].iloc[0] == "unavailable"


def test_provider_iv_is_labelled():
    chain = pd.DataFrame({"strike": [24000.0], "option_type": ["CE"], "ltp": [300.0], "bid": [299.0], "ask": [301.0],
                          "oi": [1.0], "oi_change": [0], "volume": [1], "iv": [15.0]})
    out = fno.enrich(chain, 24000.0, date(2026, 10, 30), datetime(2026, 10, 20, 10, tzinfo=IST), 0.065)
    assert out["iv_source"].iloc[0] == "provider" and not math.isnan(out["delta"].iloc[0])


def test_pcr_and_max_pain():
    ch = pd.DataFrame({"strike": [100, 100, 110, 110], "option_type": ["CE", "PE", "CE", "PE"], "oi": [10, 30, 50, 10]})
    assert fno.pcr(ch) == pytest.approx(40 / 60, abs=0.01)
    assert fno.max_pain(ch) == 100


def test_chain_storage_rejects_bad_types():
    with pytest.raises(ValueError):
        fno.save_chain("X", "2026-10-30", "2026-10-20T10:00", pd.DataFrame({"strike": [1], "option_type": ["CALL"]}),
                       "t", DataMode.HISTORICAL)


def test_migrations_idempotent_and_data_persists():
    store.save_dataset("ABC", "5m", make_session(date(2026, 10, 20), [100.0, 101.0]), DataMode.HISTORICAL, "t")
    db.set_setting("risk", {"risk_per_trade_pct": 0.25})
    db.init_db()
    db.init_db()
    db._SETTINGS.clear()
    store._invalidate()
    assert store.symbols() == ["ABC"]
    assert db.get_section("risk", {"risk_per_trade_pct": 0.5})["risk_per_trade_pct"] == 0.25
    assert db.rows("SELECT MAX(version) AS v FROM schema_version")[0]["v"] == len(db.MIGRATIONS)


def test_import_merges_and_never_mixes_modes():
    store.save_dataset("ABC", "5m", make_session(date(2026, 10, 20), [100.0, 101.0]), DataMode.HISTORICAL, "a")
    store.save_dataset("ABC", "5m", make_session(date(2026, 10, 21), [102.0, 103.0]), DataMode.HISTORICAL, "b")
    assert len(store.load("ABC", "5m")) == 4
    with pytest.raises(ValueError):
        store.save_dataset("ABC", "5m", make_session(date(2026, 10, 22), [1.0, 2.0]), DataMode.SIMULATED, "sim")


def test_resample_is_session_anchored():
    df = make_session(date(2026, 10, 20), [float(i) for i in range(1, 76)])
    r15 = store.resample(df, "15m", {"market_open": "09:15"})
    assert r15["timestamp"].iloc[0].strftime("%H:%M") == "09:15" and len(r15) == 25
    d = store.resample(df, "1d", {"market_open": "09:15"})
    assert d["open"].iloc[0] == df["open"].iloc[0] and d["close"].iloc[0] == 75.0


def test_simulated_symbols_are_labelled():
    from terminal.data import instruments, simulated
    made = simulated.generate_all(sessions=30)
    assert all(s.startswith("SIM_") for s in made)
    assert all(store.symbol_mode(s) == DataMode.SIMULATED for s in made)
    assert instruments.get("SIM_NIFTY")["source"] == "SIMULATED"
    assert store.load("SIM_NIFTY", "5m")["volume"].sum() == 0  # spot index has no volume
