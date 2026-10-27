from datetime import date, datetime
from pathlib import Path

import pytest

from terminal import db, paper
from terminal.data import instruments, store
from terminal.data.modes import DataMode
from terminal.timeutil import IST
from tests.conftest import make_session


@pytest.fixture
def market():
    closes = [100.0] * 3 + [101.0, 102.0, 103.0, 104.0, 105.0] + [105.0] * 67
    df = make_session(date(2026, 10, 20), closes)
    store.save_dataset("ABC", "5m", df, DataMode.HISTORICAL, "test")
    instruments.upsert([{"symbol": "ABC", "segment": "EQ", "exchange": "NSE", "tick_size": 0.05, "lot_size": 1}], "test")
    return df


def at(h, m):
    return datetime(2026, 10, 20, h, m, tzinfo=IST)


def test_entry_requires_confirmation(market):
    with pytest.raises(paper.ConfirmationRequired):
        paper.place_entry("ABC", "buy", 10, 99.0, 105.0, confirmed=False, as_of=at(9, 40))


def test_fill_accounting_and_target(market):
    r = paper.place_entry("ABC", "buy", 100, 99.5, 103.6, confirmed=True, as_of=at(9, 35))
    assert r.ok, r.message
    e = paper.equity(as_of=at(9, 35))
    pos = e["positions"][0]
    assert pos["qty"] == 100 and pos["avg_price"] >= 100.0  # adverse slippage
    assert e["cash"] < 100000 - 100 * 100
    events = paper.process(at(10, 0))
    assert any("target" in x for x in events)
    t = paper.trades()[0]
    assert t["exit_reason"] == "target" and t["net_pnl"] == pytest.approx(t["gross_pnl"] - t["costs"])
    assert paper.equity(as_of=at(10, 0))["equity"] == pytest.approx(100000 + t["net_pnl"], abs=0.01)


def test_flat_by_closes_intraday(market):
    paper.place_entry("ABC", "buy", 10, 90.0, 200.0, confirmed=True, as_of=at(9, 35))
    events = paper.process(at(15, 30))
    assert any("flat-by" in x for x in events)
    assert not paper.positions(as_of=at(15, 30))


def test_risk_rejection_is_recorded(market):
    r = paper.place_entry("ABC", "buy", 5000, 99.0, 110.0, confirmed=True, as_of=at(9, 35))
    assert not r.ok and r.status == "REJECTED"
    assert paper.orders()[0]["status"] == "REJECTED"


def test_index_cannot_be_traded(market):
    instruments.upsert([{"symbol": "IDX1", "segment": "IDX", "exchange": "NSE", "tick_size": 0.05, "lot_size": 1}], "t")
    store.save_dataset("IDX1", "5m", make_session(date(2026, 10, 20), [100.0] * 10), DataMode.HISTORICAL, "t")
    assert not paper.place_entry("IDX1", "buy", 1, 99.0, 102.0, confirmed=True, as_of=at(9, 40)).ok


def test_state_survives_restart(market):
    paper.place_entry("ABC", "buy", 10, 99.0, 110.0, confirmed=True, as_of=at(9, 35))
    db._SETTINGS.clear()
    store._invalidate()
    db.init_db()  # re-running migrations must not touch data
    assert paper.positions(as_of=at(9, 40))[0]["symbol"] == "ABC"
    assert len(paper.orders()) == 1


def test_manual_close_and_reset_archives(market):
    paper.place_entry("ABC", "buy", 10, 99.0, 110.0, confirmed=True, as_of=at(9, 35))
    assert paper.close_position("ABC", "manual", at(9, 50)).ok
    paper.reset_account()
    names = [r["name"] for r in db.rows("SELECT name FROM paper_accounts")]
    assert any("archived" in n for n in names) and "default" in names
    assert db.rows("SELECT COUNT(*) AS n FROM paper_trades")[0]["n"] == 1  # history kept


def test_paper_module_has_no_broker_or_network_path():
    src = Path(paper.__file__).read_text(encoding="utf-8")
    for forbidden in ("providers", "requests", "websocket", "socket", "urllib", "http"):
        assert forbidden not in src.split('"""', 2)[2], forbidden
