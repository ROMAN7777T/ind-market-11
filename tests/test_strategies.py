from datetime import date

import numpy as np
import pandas as pd
import pytest

from terminal.strategies import registry
from terminal.strategies.reference import (Breakout20D, BullFlag, OpeningRangeBreakout, Oversold, OversoldBounce,
                                           ReclaimMA20)
from tests.conftest import make_session


def orb_day(closes, highs=None):
    """Range bars 09:15/09:20/09:25 with highs 101,102,103 and lows 99,98,97, then the given closes."""
    rng_c = [100.0, 100.5, 101.0]
    rng_h = [101.0, 102.0, 103.0]
    rng_l = [99.0, 98.0, 97.0]
    hs = highs or [c + 0.2 for c in closes]
    return make_session(date(2026, 10, 20), rng_c + closes, highs=rng_h + hs, lows=rng_l + [c - 0.5 for c in closes],
                        opens=rng_c[:1] + rng_c[:-1] + [rng_c[-1]] + closes[:-1])


def sig(df, params=None, session=None):
    from tests.conftest import SESSION
    return OpeningRangeBreakout().signals(df, params, {"timeframe": "5m", "session": session or SESSION, "tick": 0.05})


def test_orb_triggers_on_first_close_above_range_high():
    df = orb_day([102.0, 103.5, 104.0, 105.0])  # 09:30 close 102 (below 103), 09:35 close 103.5 (above)
    s = sig(df)
    assert s["long_entry"].tolist().count(True) == 1
    assert s.index[s["long_entry"]][0] == 4
    assert s.loc[4, "stop_long"] == pytest.approx(100.0)  # OR midpoint (103 + 97) / 2
    assert s.loc[4, "target_r"] == 2.0


def test_orb_wick_or_equal_close_is_not_a_trigger():
    df = orb_day([103.0, 102.5], highs=[110.0, 110.0])  # close equal to the high, then wick only
    assert not sig(df)["long_entry"].any()


def test_orb_respects_entry_window():
    from tests.conftest import SESSION
    late = dict(SESSION, no_entries_after="09:30")
    df = orb_day([102.0, 104.0])  # trigger bar closes 09:40 > 09:30 cutoff
    assert not sig(df, session=late)["long_entry"].any()


def test_orb_incomplete_range_is_skipped():
    df = orb_day([104.0, 105.0]).drop(index=[1]).reset_index(drop=True)
    assert not sig(df)["long_entry"].any()


def test_orb_or_low_stop_and_short_mirror():
    df = orb_day([96.0, 95.0])
    s = sig(df, {"allow_short": True, "stop_rule": "or_low"})
    assert s["short_entry"].any()
    i = s.index[s["short_entry"]][0]
    assert s.loc[i, "stop_short"] == pytest.approx(103.0)
    assert not sig(df)["short_entry"].any()  # shorts off by default (reference is long only)


def test_orb_invalidation_option():
    df = orb_day([96.0, 104.0])  # closes below the range low, then breaks out
    assert sig(df)["long_entry"].any()
    assert not sig(df, {"invalidate_below_low": True})["long_entry"].any()


def daily(closes):
    d = pd.bdate_range("2026-01-01", periods=len(closes))
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"timestamp": d.tz_localize("Asia/Kolkata"), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1e6})


def test_breakout_20d_tag():
    closes = [100.0] * 20 + [101.0]
    assert Breakout20D().tags(daily(closes)).iloc[-1]
    assert not Breakout20D().tags(daily([100.0] * 21)).iloc[-1]


def test_bull_flag_tag():
    pole = list(np.linspace(100, 115, 11))  # +15% over 10 sessions
    flag = [115, 114, 113.5, 114.5, 114]
    closes = [100.0] * 5 + pole + flag
    assert BullFlag().tags(daily(closes)).iloc[-1]


def test_reclaim_ma20_tag():
    closes = [100.0] * 25 + [95.0, 105.0]
    t = ReclaimMA20().tags(daily(closes))
    assert t.iloc[-1] and not t.iloc[-2]


def test_oversold_and_bounce_tags():
    closes = list(np.linspace(150, 100, 30)) + [101.0]
    d = daily(closes)
    assert Oversold().tags(d).iloc[-2]
    assert OversoldBounce().tags(d).iloc[-1]
    assert not Oversold().meta.trade_capable


def test_registry_has_reference_and_terminal_sets():
    ids = {s.meta.id for s in registry.all_strategies()}
    assert {"REF_ORB", "REF_BREAKOUT20", "REF_BULLFLAG", "REF_RECLAIM20", "REF_OVERSOLD", "REF_OVERSOLD_BOUNCE"} <= ids
    assert {"T_VWAP_RETEST", "T_EMA_TREND", "T_PULLBACK", "T_RVOL_BREAKOUT", "T_SWING_TREND", "T_MEAN_REVERSION"} <= ids
    assert registry.settings("T_MEAN_REVERSION")["enabled"] is False  # disabled until tested
    assert all(not s.meta.tested for s in registry.all_strategies())


def test_strategy_settings_persist():
    registry.save("REF_ORB", False, {"target_r": 1.5})
    cfg = registry.settings("REF_ORB")
    assert cfg["enabled"] is False and cfg["params"]["target_r"] == 1.5
