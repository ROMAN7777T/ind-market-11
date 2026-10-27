"""Skill modules 3, 4, 5, 9, 10, 11 and the scanner (1)."""
import io
from datetime import date, datetime, time

import pytest

from terminal.data import simulated, store
from terminal.skills import alerts, analyst, entry_timer, exit_planner, insider_tracker, scanner, time_machine
from terminal.timeutil import IST
from tests.conftest import SESSION, make_session, random_intraday


def orb_bars():
    closes = [100.0, 100.5, 101.0, 102.0, 103.5, 104.0]
    return make_session(date(2026, 10, 20), closes, highs=[101, 102, 103, 102.2, 103.7, 104.2],
                        lows=[99, 98, 97, 101.5, 102, 103.5])


def test_entry_timer_states():
    b = orb_bars()
    assert entry_timer.status(b, "5m", datetime(2026, 10, 20, 9, 0, tzinfo=IST), SESSION)["state"] == "NOT OPEN"
    assert entry_timer.status(b, "5m", datetime(2026, 10, 20, 9, 25, tzinfo=IST), SESSION)["state"] == "RANGE FORMING"
    w = entry_timer.status(b, "5m", datetime(2026, 10, 20, 9, 35, tzinfo=IST), SESSION)
    assert w["state"] == "WAITING" and w["level"] == 103
    t = entry_timer.status(b, "5m", datetime(2026, 10, 20, 9, 40, tzinfo=IST), SESSION)
    assert t["state"] == "TRIGGERED" and t["trigger_time"] == "09:40" and t["trigger_price"] == 103.5 and not t["stale"]
    late = entry_timer.status(b, "5m", datetime(2026, 10, 20, 9, 50, tzinfo=IST), SESSION)
    assert late["state"] == "TRIGGERED" and late["stale"]
    assert entry_timer.status(b, "5m", datetime(2026, 10, 24, 10, 0, tzinfo=IST), SESSION)["state"] == "CLOSED"


def test_entry_timer_expires():
    b = make_session(date(2026, 10, 20), [100.0, 100.5, 101.0] + [100.0] * 60, highs=[101, 102, 103] + [100.5] * 60)
    assert entry_timer.status(b, "5m", datetime(2026, 10, 20, 15, 0, tzinfo=IST), SESSION)["state"] == "EXPIRED"


def test_exit_plan_default_and_refusals():
    p = exit_planner.plan(104.18, 1, "or_mid", "2R", 0.05, or_high=103.0, or_low=97.0)
    assert p.ok and p.stop == 100.0 and p.target == pytest.approx(112.55) and p.reward_risk == pytest.approx(2.0, abs=0.01)
    assert not exit_planner.plan(100.0, 1, "price", stop_price=101.0).ok
    tight = exit_planner.plan(100.0, 1, "price", stop_price=99.99, tick=0.01)
    assert not tight.ok and "too tight" in tight.refusals[0]
    late = exit_planner.plan(100.0, 1, "pct", stop_pct=1, entry_time=time(15, 15), flat_by="15:10")
    assert not late.ok
    assert not exit_planner.plan(100.0, 1, "or_mid").ok  # needs the range


def test_exit_plan_rounds_stop_away_from_entry():
    p = exit_planner.plan(100.0, 1, "price", "2R", 0.05, stop_price=98.03)
    assert p.stop == 98.0
    s = exit_planner.plan(100.0, -1, "price", "2R", 0.05, stop_price=101.97)
    assert s.stop == 102.0


def test_time_machine_deterministic_and_verdict():
    df = random_intraday(days=40, seed=9)
    last = df["timestamp"].dt.date.iloc[-1]
    day = df[df["timestamp"].dt.date == last].reset_index(drop=True)
    entry_bar = day.iloc[4]
    e = float(entry_bar["close"])
    plan = {"entry_bar_ts": entry_bar["timestamp"], "entry": e, "stop": e * 0.99, "target": e * 1.02, "direction": 1,
            "setup": "orb", "target_r": 2.0}
    a = time_machine.run(df, plan, SESSION, n=2000, seed=19)
    b = time_machine.run(df, plan, SESSION, n=2000, seed=19)
    assert a["ok"] and a["target_first_pct"] == b["target_first_pct"]
    assert a["target_first_pct"] + a["stop_first_pct"] + a["neither_pct"] == pytest.approx(100, abs=0.2)
    assert a["sessions_in_pool"] == 39  # today never in the pool
    assert a["history"]["sessions"] == 39


def test_time_machine_refuses_short_history():
    df = random_intraday(days=10, seed=9)
    bar = df.iloc[-60]
    r = time_machine.run(df, {"entry_bar_ts": bar["timestamp"], "entry": 100, "stop": 99, "target": 102}, SESSION)
    assert not r["ok"]


@pytest.mark.parametrize("tf,sf,r,expected", [(30, 30, 1, "coin flip"), (40, 20, 1, "Strongly toward the target"),
                                               (15, 60, 2, "Leans toward the stop"), (24.1, 50.5, 2, "break-even")])
def test_verdict_thresholds(tf, sf, r, expected):
    assert expected in time_machine.verdict(tf, sf, r)


def test_alerts_ring_once():
    df = make_session(date(2026, 10, 20), [100.0, 101.0, 102.0, 103.0])
    from terminal.data.modes import DataMode
    store.save_dataset("ABC", "5m", df, DataMode.HISTORICAL, "t")
    alerts.add("ABC", "above", 102.5, date="2026-10-20")
    alerts.add("ABC", "time", at_time="09:30", date="2026-10-20")
    alerts.add("ABC", "below", 50.0, date="2026-10-19")  # yesterday's: never rings
    rung = alerts.check(datetime(2026, 10, 20, 9, 35, tzinfo=IST))
    assert {a["kind"] for a in rung} == {"above", "time"}
    assert alerts.check(datetime(2026, 10, 20, 9, 35, tzinfo=IST)) == []


def test_earnings_analyst():
    csv = io.StringIO("symbol,period_end,basis,revenue,ebitda,pat,eps\n" + "\n".join(
        f"ABC,{d},consolidated,{100 + i * 10},{20 + i},{10 + i},{1 + i / 10}" for i, d in
        enumerate(["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"])))
    assert analyst.import_csv(csv) == 5
    df = analyst.analyse("ABC")
    assert df["revenue_yoy_pct"].iloc[-1] == pytest.approx(40.0)
    assert df["revenue_ttm"].iloc[-1] == 110 + 120 + 130 + 140
    assert df["pat_margin_pct"].notna().all()


def test_insider_tracker_flags_holdings():
    csv = io.StringIO("kind,symbol,person,date\nPIT,ABC,Promoter X,2026-10-01\nBULK,XYZ,Fund Y,2026-10-02\n")
    assert insider_tracker.import_csv(csv) == 2
    assert list(insider_tracker.flag_held(["abc"])["symbol"]) == ["ABC"]
    with pytest.raises(ValueError):
        insider_tracker.import_csv(io.StringIO("kind,symbol,date\nCONGRESS,ABC,2026-10-01\n"))


def test_scanner_labels_non_live_and_reports_earlier_triggers():
    simulated.generate_all(sessions=45, seed=7)
    from terminal import clock
    d = clock.default_replay_time().date()
    res = scanner.run(as_of=datetime.combine(d, time(12, 0), IST), include_idle=True)
    assert len(res)
    assert res["status"].str.contains("NOT A LIVE SIGNAL|INSUFFICIENT|NO VOLUME").all()
    trig = res[res["setup_state"] == "TRIGGERED"]
    assert trig["quality"].between(0, 100).all() if len(trig) else True
    tags = scanner.daily_tags(as_of=datetime.combine(d, time(9, 0), IST))
    assert {"breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"} <= set(tags.columns)
