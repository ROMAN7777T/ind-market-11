from datetime import date

import pandas as pd
import pytest

from terminal import backtest
from terminal.strategies.base import Strategy, StrategyMeta, empty_frame
from terminal.strategies import registry
from tests.conftest import SESSION, make_session, random_intraday


class OneShot(Strategy):
    """Signals a long on bar `at` with a fixed stop and 2R target."""
    meta = StrategyMeta(id="TEST", name="test", group="TEST", styles=["intraday"], timeframes=["5m"], default_enabled=True,
                        trade_capable=True, tested=False, needs_volume=False, summary="", rules={})

    def __init__(self, at, stop, r=2.0):
        self.at, self.stop, self.r = at, stop, r

    def signals(self, df, params, ctx):
        out = empty_frame(df)
        out.loc[self.at, "long_entry"] = True
        out.loc[self.at, "stop_long"] = self.stop
        out["target_r"] = self.r
        return out


def settings(**kw):
    base = dict(timeframe="5m", session=SESSION, slippage_pct=0.0, slippage_ticks=0, oos_fraction=0.0, sizing="fixed_qty",
                fixed_qty=10, max_leverage=10.0)
    base.update(kw)
    return backtest.BTSettings(**base)


def bars(opens, highs, lows, closes):
    df = make_session(date(2026, 10, 20), closes, highs=highs, lows=lows, opens=opens)
    return df


def test_fill_at_next_open_not_signal_close():
    df = bars([100, 100, 105, 106], [101, 101, 107, 107], [99, 99, 104, 105], [100, 100, 106, 106])
    r = backtest.run(df, OneShot(1, 95), None, settings())
    assert r.trades.iloc[0]["entry_price"] == 105  # bar 2 open, not bar 1 close


def test_bar_touching_both_stop_and_target_counts_as_stop():
    # entry 100 at bar 2 open, stop 98, target 104; bar 3 touches both
    df = bars([100, 100, 100, 100], [100.5, 100.5, 101, 105], [99.5, 99.5, 99, 97], [100, 100, 100, 100])
    r = backtest.run(df, OneShot(1, 98), None, settings())
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "stop" and t["exit_price"] == 98


def test_gap_through_stop_fills_at_open():
    df = bars([100, 100, 100, 95], [100.5, 100.5, 100.5, 96], [99.5, 99.5, 99.5, 94], [100, 100, 100, 95])
    r = backtest.run(df, OneShot(1, 98), None, settings())
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "gap_stop" and t["exit_price"] == 95


def test_intraday_flat_by_and_never_overnight():
    closes = [100.0] * 75
    df = make_session(date(2026, 10, 20), closes)
    df2 = make_session(date(2026, 10, 21), closes)
    both = pd.concat([df, df2], ignore_index=True)
    r = backtest.run(both, OneShot(5, 90, r=50), None, settings())
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "time"
    assert t["exit_ts"].strftime("%H:%M") == "15:10" and t["exit_ts"].date() == date(2026, 10, 20)


def test_costs_reduce_net_pnl():
    df = bars([100, 100, 100, 100], [100.5, 100.5, 101, 105], [99.5, 99.5, 99.5, 99.5], [100, 100, 100, 104])
    r = backtest.run(df, OneShot(1, 98), None, settings())
    t = r.trades.iloc[0]
    assert t["exit_reason"] == "target"
    assert t["gross_pnl"] == pytest.approx(40)
    assert t["costs"] > 0 and t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["costs"])


def test_risk_sizing_and_lot_rounding():
    df = bars([100, 100, 100, 100], [100.5, 100.5, 100.5, 100.5], [99.5, 99.5, 99.5, 99.5], [100] * 4)
    r = backtest.run(df, OneShot(1, 98), None, settings(sizing="risk_pct", risk_pct=1.0, lot_size=25, initial_capital=100000))
    q = r.trades.iloc[0]["qty"]
    assert q % 25 == 0 and q * 2 <= 1000


def test_oos_split_and_metrics():
    df = random_intraday(days=60, seed=3)
    r = backtest.run(df, registry.get("REF_ORB"), None, settings(oos_fraction=0.3, sizing="risk_pct"))
    assert r.metrics["trades"] == r.metrics_is.get("trades", 0) + r.metrics_oos.get("trades", 0)
    for k in ("net_pnl", "win_rate_pct", "expectancy", "max_drawdown_pct", "exposure_pct"):
        assert k in r.metrics


def test_tag_only_strategy_cannot_backtest():
    with pytest.raises(ValueError):
        backtest.run(random_intraday(5), registry.get("REF_OVERSOLD"), None, settings(timeframe="1d"))


def test_walk_forward_runs():
    df = random_intraday(days=80, seed=5)
    wf = backtest.walk_forward(df, registry.get("REF_ORB"), None, settings(sizing="risk_pct"), folds=3)
    assert len(wf) >= 2
    assert {"fold", "chosen_params", "expectancy"} <= set(wf.columns)
