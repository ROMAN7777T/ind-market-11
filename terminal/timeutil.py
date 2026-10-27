"""Indian Standard Time and NSE session status.

IST has no daylight saving, so a fixed +05:30 offset is exact and needs no tz database.
Holidays are not hardcoded: they come from the holiday calendar imported in Data Manager.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


def now_ist() -> datetime:
    return datetime.now(IST)


def parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def to_ist(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def market_status(now: datetime, session: dict, holidays: set[date] | None, holidays_loaded: bool) -> dict:
    """Return the NSE cash-market session status for `now`.

    `holidays_loaded` False means the calendar is unknown: a weekday is reported as a
    trading day with a warning rather than silently assumed correct.
    """
    now = to_ist(now)
    d = now.date()
    t = now.time()
    warning = None if holidays_loaded else "Holiday calendar not loaded: holidays are not detected."
    if d.weekday() >= 5:
        return {"status": "CLOSED", "label": "Closed (weekend)", "warning": warning}
    if holidays and d in holidays:
        return {"status": "CLOSED", "label": "Closed (NSE holiday)", "warning": warning}
    pre_s, pre_e = parse_hhmm(session["pre_open_start"]), parse_hhmm(session["pre_open_end"])
    op, cl = parse_hhmm(session["market_open"]), parse_hhmm(session["market_close"])
    if pre_s <= t < pre_e:
        label, status = "Pre-open auction", "PRE_OPEN"
    elif pre_e <= t < op:
        label, status = "Pre-open (order matching)", "PRE_OPEN"
    elif op <= t < cl:
        label, status = "Market open", "OPEN"
    elif t < pre_s:
        label, status = "Pre-market", "CLOSED"
    else:
        label, status = "Market closed", "CLOSED"
    return {"status": status, "label": label, "warning": warning}


def in_window(t: time, start: str | None, end: str | None) -> bool:
    if start and t < parse_hhmm(start):
        return False
    if end and t > parse_hhmm(end):
        return False
    return True
