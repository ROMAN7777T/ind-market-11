from datetime import date

import numpy as np
import pandas as pd
import pytest

from terminal import indicators as ind
from tests.conftest import make_session


def test_sma_and_warmup():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(s, 3)
    assert out.isna().sum() == 2
    assert out.iloc[-1] == 4


def test_ema_warmup_and_value():
    s = pd.Series(range(1, 21), dtype=float)
    out = ind.ema(s, 10)
    assert out.iloc[:9].isna().all()
    alpha = 2 / 11
    manual = s.iloc[0]
    for v in s.iloc[1:]:
        manual = alpha * v + (1 - alpha) * manual
    assert out.iloc[-1] == pytest.approx(manual)


def test_rsi_wilder_bounds():
    up = pd.Series(np.arange(1, 40, dtype=float))
    assert ind.rsi(up, 14).iloc[-1] == 100
    down = pd.Series(np.arange(40, 1, -1, dtype=float))
    assert ind.rsi(down, 14).iloc[-1] == pytest.approx(0)
    assert ind.rsi(up, 14).iloc[:14].isna().all()


def test_rsi_matches_independent_wilder_calculation():
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
              46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
    diffs = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in diffs[:14]) / 14
    loss = sum(max(-d, 0) for d in diffs[:14]) / 14
    expected = [100 - 100 / (1 + gain / loss)]
    for d in diffs[14:]:
        gain = (gain * 13 + max(d, 0)) / 14
        loss = (loss * 13 + max(-d, 0)) / 14
        expected.append(100 - 100 / (1 + gain / loss))
    r = ind.rsi(pd.Series(closes), 14)
    assert r.iloc[14:].tolist() == pytest.approx(expected)


def test_atr_true_range_uses_prev_close():
    df = pd.DataFrame({"high": [10, 12, 11.0], "low": [9, 11, 8.0], "close": [9.5, 11.5, 9.0], "open": [9, 11, 11.0]})
    tr = ind.true_range(df)
    assert list(tr) == [1.0, 2.5, 3.5]


def test_vwap_resets_each_session():
    a = make_session(date(2026, 10, 20), [100, 101, 102])
    b = make_session(date(2026, 10, 21), [200, 201, 202])
    df = pd.concat([a, b], ignore_index=True)
    v = ind.vwap(df)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    assert v.iloc[3] == pytest.approx(tp.iloc[3])  # first bar of day 2 = its own typical price


def test_vwap_nan_without_volume():
    df = make_session(date(2026, 10, 20), [100, 101, 102], volume=0.0)
    assert ind.vwap(df).isna().all()


def test_bollinger_width():
    s = pd.Series([10.0] * 25)
    bb = ind.bollinger(s, 20)
    assert bb["bb_upper"].iloc[-1] == bb["bb_lower"].iloc[-1] == 10


def test_relative_volume_uses_prior_sessions_only():
    days = [make_session(date(2026, 10, d), [100, 101], volume=100.0) for d in (12, 13, 14, 15, 16, 19)]
    df = pd.concat(days, ignore_index=True)
    df.loc[df.index[-1], "volume"] = 300.0
    rv = ind.relative_volume(df, 5, True)
    assert rv.iloc[-1] == pytest.approx(3.0)  # today's bar vs prior 5 same-slot bars, today excluded
    assert rv.iloc[:2].isna().all()


@pytest.mark.parametrize("price,tick,direction,expected", [
    (100.07, 0.05, "down", 100.05), (100.07, 0.05, "up", 100.10), (100.074, 0.05, "nearest", 100.05),
    (19.999, 0.01, "down", 19.99), (250.0, 0.05, "down", 250.0)])
def test_round_to_tick(price, tick, direction, expected):
    assert ind.round_to_tick(price, tick, direction) == pytest.approx(expected)


def test_round_to_tick_requires_tick():
    with pytest.raises(ValueError):
        ind.round_to_tick(100, 0)
