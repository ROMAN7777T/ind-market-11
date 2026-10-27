"""Look-ahead protection: a signal at bar i must not change when future bars are added."""
import pandas as pd
import pytest

from terminal.data.store import resample
from terminal.strategies import registry
from tests.conftest import SESSION, random_intraday

COLS = ["long_entry", "short_entry", "stop_long", "stop_short", "level_long", "level_short", "bias", "exit_long", "exit_short"]


def frames():
    df5 = random_intraday(days=90, seed=11)
    return {"5m": df5, "1m": df5, "15m": resample(df5, "15m", SESSION), "1d": resample(df5, "1d", SESSION)}


@pytest.mark.parametrize("strategy", registry.all_strategies(), ids=lambda s: s.meta.id)
def test_signals_do_not_use_future_bars(strategy):
    data = frames()
    for tf in strategy.meta.timeframes:
        if tf == "1m":
            continue
        df = data[tf]
        params = dict(strategy.defaults())
        if "allow_short" in params:
            params["allow_short"] = True
        ctx = {"timeframe": tf, "session": SESSION, "tick": 0.05}
        full = strategy.signals(df, params, ctx)
        for cut in (len(df) // 2, len(df) - 37, len(df) - 5):
            part = strategy.signals(df.iloc[:cut].reset_index(drop=True), params, ctx)
            a = full.iloc[:cut][COLS].reset_index(drop=True)
            b = part[COLS].reset_index(drop=True)
            pd.testing.assert_frame_equal(a, b, check_dtype=False, obj=f"{strategy.meta.id} {tf} cut={cut}")
