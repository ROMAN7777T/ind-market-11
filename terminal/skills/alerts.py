"""Skill 9 - Price Alerts. Each alert rings once. An alert is a fact, never an order.

Kinds: above, below, stop, target, pct_move (from previous close), time (IST clock).
Plan alerts are dated so yesterday's stop never rings today.
"""
from __future__ import annotations

from datetime import datetime

from .. import clock, db
from ..data import store

KINDS = ("above", "below", "stop", "target", "pct_move", "time")


def add(symbol: str, kind: str, level: float | None = None, at_time: str | None = None, date: str | None = None,
        note: str = "") -> int:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if kind == "time" and not at_time:
        raise ValueError("A time alert needs HH:MM")
    if kind != "time" and level is None:
        raise ValueError("A level is required")
    return db.execute("INSERT INTO alerts (symbol, kind, level, at_time, date, active, note) VALUES (?, ?, ?, ?, ?, 1, ?)",
                      (symbol.upper(), kind, level, at_time, date, note))


def add_from_plan(symbol: str, stop: float, target: float, flat_by: str, date: str, direction: int = 1) -> list[int]:
    s_kind, t_kind = ("stop", "target")
    return [
        add(symbol, s_kind, stop, date=date, note=f"Plan stop ({'long' if direction > 0 else 'short'})"),
        add(symbol, t_kind, target, date=date, note="Plan target"),
        add(symbol, "time", at_time=flat_by, date=date, note="Flat by: close any open intraday position"),
    ]


def list_alerts(active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM alerts" + (" WHERE active = 1" if active_only else "") + " ORDER BY id DESC"
    return db.rows(sql)


def delete(alert_id: int) -> None:
    db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))


def reset(alert_id: int) -> None:
    db.execute("UPDATE alerts SET active = 1, rang_at = NULL WHERE id = ?", (alert_id,))


def check(as_of: datetime | None = None) -> list[dict]:
    as_of = as_of or clock.now()
    rung = []
    for a in list_alerts(active_only=True):
        if a["date"] and a["date"] != as_of.date().isoformat():
            continue
        msg = None
        if a["kind"] == "time":
            if as_of.weekday() < 5 and as_of.strftime("%H:%M") >= a["at_time"]:
                msg = f"{a['at_time']} IST reached. {a['note'] or ''}".strip()
        else:
            q = clock.price_at(a["symbol"], as_of)
            if not q:
                continue
            px = q["price"]
            if a["kind"] in ("above", "target") and px >= a["level"]:
                msg = f"{a['symbol']} {px:.2f} at or above {a['level']:.2f}"
            elif a["kind"] in ("below", "stop") and px <= a["level"]:
                msg = f"{a['symbol']} {px:.2f} at or below {a['level']:.2f}"
            elif a["kind"] == "pct_move":
                daily = store.load(a["symbol"], "1d")
                prev = daily[daily["timestamp"].dt.date < as_of.date()]
                if len(prev):
                    move = (px / prev["close"].iloc[-1] - 1) * 100
                    if abs(move) >= abs(a["level"]):
                        msg = f"{a['symbol']} moved {move:+.2f}% from the previous close"
            if msg:
                msg += f" (bar {q['bar_ts']:%H:%M}, {q['mode']} data)"
        if msg:
            db.execute("UPDATE alerts SET active = 0, rang_at = ? WHERE id = ?", (as_of.isoformat(timespec="seconds"), a["id"]))
            rung.append({"id": a["id"], "symbol": a["symbol"], "kind": a["kind"], "message": msg})
    return rung
