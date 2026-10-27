from datetime import datetime

from terminal.config import DEFAULT_RISK
from terminal.data import instruments
from terminal.skills import risk as R
from terminal.skills import sizer
from terminal.timeutil import IST
from tests.conftest import SESSION

T = datetime(2026, 10, 20, 10, 0, tzinfo=IST)


def pf(**kw):
    base = dict(equity=100000.0, cash=100000.0, start_of_day_equity=100000.0)
    base.update(kw)
    return R.PortfolioState(**base)


def req(**kw):
    base = dict(symbol="ABC", side="buy", qty=20, price=1000.0, stop=990.0, target=1020.0, as_of=T, data_mode="HISTORICAL")
    base.update(kw)
    return R.OrderRequest(**base)


def check(r, p=None, **risk):
    return R.check(r, p or pf(), dict(DEFAULT_RISK, **risk), SESSION, record=False)


def test_valid_entry_passes():
    d = check(req())
    assert d.passed, d.blocks
    assert any("HISTORICAL" in w for w in d.warnings)


def test_per_trade_loss_limit():
    d = check(req(qty=60))  # 60 x 10 = 600 > 500 (0.5% of 1,00,000)
    assert not d.passed and any(b.startswith("loss") for b in d.blocks)


def test_stop_required_and_side():
    assert any(b.startswith("stop") for b in check(req(stop=None)).blocks)
    assert any("wrong side" in b for b in check(req(stop=1005.0)).blocks)


def test_reward_risk_minimum():
    d = check(req(target=1010.0))  # 1R < 1.5
    assert any("reward:risk" in b for b in d.blocks)


def test_daily_loss_lockout():
    d = check(req(), pf(realized_today=-1600.0, equity=98400.0, cash=98400.0))
    assert any("lockout" in b for b in d.blocks)


def test_aggregate_open_risk():
    pos = [{"symbol": "X", "qty": 10, "avg_price": 1, "stop": 0.5, "planned_risk": 700.0},
           {"symbol": "Y", "qty": 10, "avg_price": 1, "stop": 0.5, "planned_risk": 700.0}]
    d = check(req(), pf(positions=pos))
    assert any("aggregate risk" in b for b in d.blocks)


def test_max_positions_and_trades_and_duplicates():
    pos = [{"symbol": s, "qty": 1, "avg_price": 1, "stop": 0.9, "planned_risk": 0.1} for s in ("A", "B", "C")]
    assert any(b.startswith("positions") for b in check(req(), pf(positions=pos)).blocks)
    assert any(b.startswith("trades") for b in check(req(), pf(entries_today=["A", "B", "C"])).blocks)
    assert any(b.startswith("duplicate") for b in check(req(), pf(entries_today=["ABC"])).blocks)


def test_no_averaging_down():
    pos = [{"symbol": "ABC", "qty": 10, "avg_price": 1100, "stop": 1050, "planned_risk": 500}]
    assert any(b.startswith("averaging") for b in check(req(), pf(positions=pos)).blocks)


def test_no_martingale_override():
    assert any(b.startswith("martingale") for b in check(req(risk_pct_override=1.0)).blocks)


def test_shorts_blocked_by_default():
    d = check(req(side="sell", stop=1010.0, target=980.0))
    assert any(b.startswith("short") for b in d.blocks)
    assert check(req(side="sell", stop=1010.0, target=980.0), allow_short=True).passed


def test_entry_window():
    early = req(as_of=datetime(2026, 10, 20, 9, 20, tzinfo=IST))
    assert any(b.startswith("window") for b in check(early).blocks)


def test_exit_never_blocked_by_limits():
    pos = [{"symbol": "ABC", "qty": 20, "avg_price": 1000, "stop": 990, "planned_risk": 200}]
    late = req(side="sell", intent="exit", stop=None, target=None, as_of=datetime(2026, 10, 20, 15, 20, tzinfo=IST))
    d = check(late, pf(positions=pos, realized_today=-5000.0, entries_today=["A", "B", "C"]))
    assert d.passed, d.blocks


def test_exit_must_reduce_position():
    d = check(req(side="sell", intent="exit"))
    assert not d.passed


def test_fno_requires_metadata():
    d = check(req(symbol="NIFTYFUT", segment="FUT", lot_size=75, qty=75))
    assert any(b.startswith("metadata") for b in d.blocks)
    instruments.upsert([{"symbol": "NIFTYFUT", "segment": "FUT", "exchange": "NSE", "lot_size": 75, "tick_size": 0.05,
                         "expiry": "2026-10-21"}], "test")
    d2 = check(req(symbol="NIFTYFUT", segment="FUT", lot_size=75, qty=75, price=100.0, stop=99.5, target=101.0))
    assert not any(b.startswith("metadata") for b in d2.blocks)
    assert any("expiry" in w for w in d2.warnings)


def test_lot_multiple_enforced():
    assert any("multiple of the lot size" in b for b in check(req(lot_size=25, qty=30)).blocks)


def test_rejections_are_recorded():
    from terminal import db
    R.check(req(qty=999), pf(), dict(DEFAULT_RISK), SESSION, record=True)
    rows = db.rows("SELECT decision, reasons FROM risk_log")
    assert rows and rows[-1]["decision"] == "BLOCK" and "loss" in rows[-1]["reasons"]


# ---------- sizer ----------

def test_sizer_takes_smallest_limit():
    s = sizer.size(1000.0, 990.0, 100000.0, 100000.0, dict(DEFAULT_RISK), target=1020.0)
    assert s.ok and s.deciding_limit == "max loss"
    assert s.qty * 10 + s.est_costs <= 500 + 1e-6


def test_sizer_lot_rounding_and_refusal():
    s = sizer.size(100.0, 99.0, 100000.0, 100000.0, dict(DEFAULT_RISK), lot_size=75, segment="FUT", target=102.0)
    assert s.ok and s.qty % 75 == 0
    big = sizer.size(100.0, 90.0, 100000.0, 100000.0, dict(DEFAULT_RISK), lot_size=75, segment="FUT", target=120.0)
    assert not big.ok and "Refused" in big.refusals[0]


def test_sizer_uses_higher_fresh_price():
    s = sizer.size(1000.0, 990.0, 100000.0, 100000.0, dict(DEFAULT_RISK), fresh_price=1005.0, target=1040.0)
    assert s.sized_at == 1005.0


def test_sizer_refuses_when_move_already_happened():
    s = sizer.size(1000.0, 990.0, 100000.0, 100000.0, dict(DEFAULT_RISK), fresh_price=1025.0, target=1020.0)
    assert not s.ok
