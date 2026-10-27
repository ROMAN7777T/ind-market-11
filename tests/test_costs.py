import pytest

from terminal import costs


def test_intraday_equity_components():
    m = costs.load_model()
    buy = costs.order_costs("buy", 1000.0, 100, "EQ", "INTRADAY", m)  # turnover 1,00,000
    assert buy.brokerage == pytest.approx(20.0)  # 0.03% = 30, capped at 20
    assert buy.stt == 0
    assert buy.stamp == pytest.approx(3.0)
    assert buy.gst == pytest.approx((buy.brokerage + buy.exchange + buy.sebi) * 0.18)
    sell = costs.order_costs("sell", 1000.0, 100, "EQ", "INTRADAY", m)
    assert sell.stt == pytest.approx(25.0)
    assert sell.stamp == 0


def test_delivery_stt_both_sides():
    m = costs.load_model()
    assert costs.order_costs("buy", 500.0, 10, "EQ", "DELIVERY", m).stt == pytest.approx(5.0)
    assert costs.order_costs("sell", 500.0, 10, "EQ", "DELIVERY", m).stt == pytest.approx(5.0)


def test_options_flat_brokerage_on_premium():
    m = costs.load_model()
    c = costs.order_costs("sell", 100.0, 75, "OPT", "INTRADAY", m)
    assert c.brokerage == 20.0
    assert c.stt == pytest.approx(7500 * 0.001)


def test_round_trip_positive():
    assert costs.round_trip(100, 101, 50) > 0


def test_slippage_is_adverse_and_on_tick():
    assert costs.slip(100.0, "buy", 0.03, 1, 0.05) == pytest.approx(100.1)  # 100 + 0.03 + 0.05 = 100.08 -> up to 100.10
    assert costs.slip(100.0, "sell", 0.03, 1, 0.05) == pytest.approx(99.9)
    assert costs.slip(100.0, "buy", 0.0, 0, 0.05) == pytest.approx(100.0)
