from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from terminal.data.validation import drop_incomplete, is_stale, normalize, validate
from terminal.timeutil import IST, market_status
from tests.conftest import make_session


def test_invalid_rows_dropped_and_reported(session):
    df = make_session(date(2026, 10, 20), [100, 101, 102, 103])
    df.loc[1, "high"] = 50  # high below low
    df.loc[2, "close"] = None
    df = pd.concat([df, df.iloc[[0]]])  # duplicate
    out, rep = validate(df, "5m", session)
    assert len(out) == 2
    assert rep.invalid_ohlc == 1 and rep.missing_values == 1 and rep.duplicates == 1
    assert rep.issues


def test_outside_session_and_weekend_dropped(session):
    df = make_session(date(2026, 10, 20), [100, 101], start="08:55")  # pre-market bars
    sat = make_session(date(2026, 10, 24), [100, 101])
    out, rep = validate(pd.concat([df, sat]), "5m", session)
    assert len(out) == 0 or out["timestamp"].dt.weekday.max() < 5
    assert rep.outside_session >= 3


def test_missing_bars_counted(session):
    full = make_session(date(2026, 10, 20), [100.0] * 75)
    gappy = full.drop(index=[10, 11, 12])
    _, rep = validate(gappy, "5m", session)
    assert rep.missing_bars == 3
    assert rep.full_sessions == 0
    _, rep2 = validate(full, "5m", session)
    assert rep2.full_sessions == 1


def test_naive_timestamps_are_ist_and_utc_converted():
    naive = pd.DataFrame({"timestamp": ["2026-10-20 09:15"], "open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
    assert normalize(naive)["timestamp"].iloc[0].utcoffset() == timedelta(hours=5, minutes=30)
    utc = naive.assign(timestamp=["2026-10-20T03:45:00Z"])
    assert normalize(utc)["timestamp"].iloc[0].hour == 9


def test_missing_columns_rejected():
    with pytest.raises(ValueError):
        normalize(pd.DataFrame({"timestamp": [1], "close": [1]}))


def test_drop_incomplete_bar():
    df = make_session(date(2026, 10, 20), [100, 101, 102])
    now = datetime(2026, 10, 20, 9, 27, tzinfo=IST)  # 09:25 bar still forming
    assert len(drop_incomplete(df, "5m", now)) == 2


def test_stale_detection():
    last = datetime(2026, 10, 20, 10, 0, tzinfo=IST)
    assert not is_stale(last, "5m", last + timedelta(minutes=10))
    assert is_stale(last, "5m", last + timedelta(minutes=30))


def test_market_status_reports_unknown_holidays(session):
    st = market_status(datetime(2026, 10, 20, 10, 0, tzinfo=IST), session, set(), False)
    assert st["status"] == "OPEN" and st["warning"]
    hol = market_status(datetime(2026, 10, 20, 10, 0, tzinfo=IST), session, {date(2026, 10, 20)}, True)
    assert hol["status"] == "CLOSED"
    assert market_status(datetime(2026, 10, 24, 10, 0, tzinfo=IST), session, set(), True)["status"] == "CLOSED"
    assert market_status(datetime(2026, 10, 20, 9, 3, tzinfo=IST), session, set(), True)["status"] == "PRE_OPEN"
