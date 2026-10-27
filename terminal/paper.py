"""Skill 8 - Order Desk, PAPER ONLY.

This module simulates orders against locally stored candles. It has no network code and
imports nothing from `terminal.providers`; there is no code path from here to a broker.
Every entry needs explicit confirmation (`confirmed=True`, set by the UI only after the user
types CONFIRM) and must pass the central Risk Manager. Exits are never blocked.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from . import clock
from . import costs as costmod
from . import db
from .config import DEFAULT_PAPER, DEFAULT_SESSION
from .data import instruments, store
from .skills import risk as riskmod
from .timeutil import parse_hhmm, to_ist

PAPER_ONLY = True


class ConfirmationRequired(Exception):
    pass


@dataclass
class OrderResult:
    ok: bool
    order_id: int | None
    status: str
    message: str
    decision: riskmod.Decision | None = None
    fill_price: float | None = None


def paper_settings() -> dict:
    return db.get_section("paper", DEFAULT_PAPER)


def account_id(name: str = "default") -> int:
    rs = db.rows("SELECT id FROM paper_accounts WHERE name = ?", (name,))
    if rs:
        return rs[0]["id"]
    cap = float(paper_settings()["initial_capital"])
    return db.execute("INSERT INTO paper_accounts (name, initial_capital, cash, created) VALUES (?, ?, ?, ?)",
                      (name, cap, cap, db.now_str()))


def reset_account(name: str = "default", capital: float | None = None) -> None:
    """Start a fresh paper account. Old trades are kept under a renamed archived account."""
    aid = account_id(name)
    stamp = db.now_str().replace(":", "")
    db.execute("UPDATE paper_accounts SET name = ? WHERE id = ?", (f"{name} (archived {stamp})", aid))
    if capital:
        s = paper_settings()
        s["initial_capital"] = float(capital)
        db.set_setting("paper", s)
    account_id(name)


def _segment(symbol: str) -> tuple[str, int]:
    inst = instruments.get(symbol)
    if not inst:
        return "EQ", 1
    seg = inst["segment"] if inst["segment"] != "IDX" else "IDX"
    return seg, int(inst["lot_size"] or 1)


def positions(aid: int | None = None, as_of: datetime | None = None) -> list[dict]:
    aid = aid or account_id()
    as_of = as_of or clock.now()
    out = []
    for p in db.rows("SELECT * FROM paper_positions WHERE account_id = ?", (aid,)):
        q = clock.price_at(p["symbol"], as_of)
        last = q["price"] if q else None
        p["last_price"] = last
        p["price_ts"] = str(q["bar_ts"]) if q else None
        p["unrealized"] = round((last - p["avg_price"]) * p["qty"], 2) if last is not None else None
        p["direction"] = "LONG" if p["qty"] > 0 else "SHORT"
        out.append(p)
    return out


def equity(aid: int | None = None, as_of: datetime | None = None) -> dict:
    aid = aid or account_id()
    acct = db.rows("SELECT * FROM paper_accounts WHERE id = ?", (aid,))[0]
    pos = positions(aid, as_of)
    mv = sum((p["last_price"] if p["last_price"] is not None else p["avg_price"]) * p["qty"] for p in pos)
    unreal = sum(p["unrealized"] or 0 for p in pos)
    return {"cash": round(acct["cash"], 2), "market_value": round(mv, 2), "equity": round(acct["cash"] + mv, 2),
            "unrealized": round(unreal, 2), "initial_capital": acct["initial_capital"], "positions": pos}


def _start_of_day(aid: int, day: str, eq_now: float) -> float:
    rs = db.rows("SELECT start_equity FROM paper_daily WHERE account_id = ? AND date = ?", (aid, day))
    if rs:
        return rs[0]["start_equity"]
    db.execute("INSERT INTO paper_daily (account_id, date, start_equity) VALUES (?, ?, ?)", (aid, day, eq_now))
    return eq_now


def portfolio_state(aid: int | None = None, as_of: datetime | None = None) -> riskmod.PortfolioState:
    aid = aid or account_id()
    as_of = as_of or clock.now()
    e = equity(aid, as_of)
    day = as_of.date().isoformat()
    realized = db.rows("SELECT COALESCE(SUM(net_pnl), 0) AS s FROM paper_trades WHERE account_id = ? AND substr(exit_ts, 1, 10) = ?",
                       (aid, day))[0]["s"]
    entries = [r["symbol"] for r in db.rows(
        "SELECT symbol FROM paper_orders WHERE account_id = ? AND intent = 'entry' AND status = 'FILLED' AND substr(fill_ts, 1, 10) = ?",
        (aid, day))]
    sod = _start_of_day(aid, day, e["equity"] - e["unrealized"] - realized)
    return riskmod.PortfolioState(
        equity=e["equity"], cash=e["cash"], start_of_day_equity=sod,
        positions=[{"symbol": p["symbol"], "qty": p["qty"], "avg_price": p["avg_price"], "stop": p["stop"],
                    "planned_risk": p["planned_risk"]} for p in e["positions"]],
        realized_today=realized, unrealized=e["unrealized"], entries_today=entries)


def _record_order(aid, as_of, symbol, side, qty, otype, status, intent, strategy=None, reason="", limit=None,
                  stop=None, target=None, fill=None, fill_ts=None, costs=None, product=None, mode=None) -> int:
    return db.execute(
        """INSERT INTO paper_orders (account_id, ts, symbol, side, qty, order_type, limit_price, stop_price, target_price,
           status, strategy, reason, fill_price, fill_ts, costs, product, data_mode, intent)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (aid, db.iso(as_of), symbol, side, qty, otype, limit, stop, target, status, strategy, reason, fill,
         fill_ts, costs, product, mode, intent))


def place_entry(symbol: str, side: str, qty: int, stop: float | None, target: float | None, confirmed: bool,
                strategy: str | None = "MANUAL", product: str = "INTRADAY", order_type: str = "MARKET",
                limit_price: float | None = None, as_of: datetime | None = None, aid: int | None = None) -> OrderResult:
    if not confirmed:
        raise ConfirmationRequired("Paper entries need explicit confirmation from the user.")
    aid = aid or account_id()
    as_of = as_of or clock.now()
    q = clock.price_at(symbol, as_of)
    seg, lot = _segment(symbol)
    if seg == "IDX":
        return OrderResult(False, None, "REJECTED", "Indices cannot be traded directly: use index futures or options.")
    if q is None:
        oid = _record_order(aid, as_of, symbol, side, qty, order_type, "REJECTED", "entry", strategy,
                            "No valid price at the clock time (missing or stale data)", limit_price, stop, target, product=product)
        return OrderResult(False, oid, "REJECTED", "No valid price for this symbol at the current clock time.")
    ps = paper_settings()
    ref = q["price"] if order_type == "MARKET" else float(limit_price)
    tick = instruments.tick_size(symbol) or 0.05
    daily = store.load(symbol, "1d")
    gap = None
    today = daily[daily["timestamp"].dt.date == as_of.date()]
    prev = daily[daily["timestamp"].dt.date < as_of.date()]
    if len(today) and len(prev):
        gap = (today["open"].iloc[0] / prev["close"].iloc[-1] - 1) * 100
    atv = float((prev["close"] * prev["volume"]).tail(20).mean()) if len(prev) and prev["volume"].sum() > 0 else None
    req = riskmod.OrderRequest(symbol=symbol, side=side, qty=int(qty), price=ref, intent="entry", stop=stop,
                               target=target, strategy=strategy, segment=seg, product=product, lot_size=lot,
                               as_of=as_of, data_mode=q["mode"] or "SIMULATED", gap_pct=gap, avg_traded_value=atv)
    dec = riskmod.check(req, portfolio_state(aid, as_of))
    if not dec.passed:
        oid = _record_order(aid, as_of, symbol, side, qty, order_type, "REJECTED", "entry", strategy,
                            "; ".join(dec.blocks), limit_price, stop, target, product=product, mode=q["mode"])
        return OrderResult(False, oid, "REJECTED", "Blocked by the risk manager.", dec)
    if order_type == "LIMIT":
        oid = _record_order(aid, as_of, symbol, side, qty, "LIMIT", "OPEN", "entry", strategy, "Waiting for price",
                            limit_price, stop, target, product=product, mode=q["mode"])
        return OrderResult(True, oid, "OPEN", f"Paper limit order open at {limit_price}.", dec)
    fill = costmod.slip(q["price"], side, ps["slippage_pct"], ps["slippage_ticks"], tick)
    oid = _fill_entry(aid, as_of, symbol, side, qty, fill, q["bar_ts"], stop, target, strategy, product, seg, lot,
                      q["mode"], "MARKET")
    return OrderResult(True, oid, "FILLED", f"Paper {side} {qty} {symbol} filled at {fill:.2f} (simulated).", dec, fill)


def _fill_entry(aid, as_of, symbol, side, qty, fill, bar_ts, stop, target, strategy, product, seg, lot, mode,
                otype, order_id: int | None = None) -> int:
    c = costmod.order_costs(side, fill, qty, seg, product).total
    direction = 1 if side == "buy" else -1
    planned = abs(fill - stop) * qty if stop else 0.0
    with db.session() as conn:
        if order_id is None:
            cur = conn.execute(
                """INSERT INTO paper_orders (account_id, ts, symbol, side, qty, order_type, stop_price, target_price,
                   status, strategy, reason, fill_price, fill_ts, costs, product, data_mode, intent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'FILLED', ?, 'Simulated fill', ?, ?, ?, ?, ?, 'entry')""",
                (aid, db.iso(as_of), symbol, side, qty, otype, stop, target, strategy, fill, db.iso(as_of), c, product, mode))
            order_id = cur.lastrowid
        else:
            conn.execute("UPDATE paper_orders SET status='FILLED', fill_price=?, fill_ts=?, costs=? WHERE id=?",
                         (fill, db.iso(as_of), c, order_id))
        conn.execute("UPDATE paper_accounts SET cash = cash - ? WHERE id = ?", (direction * fill * qty + c, aid))
        conn.execute(
            """INSERT INTO paper_positions (account_id, symbol, qty, avg_price, stop, target, strategy, opened_ts, product,
               lot_size, planned_risk, entry_costs, segment, last_checked_ts, data_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, symbol, direction * qty, fill, stop, target, strategy, db.iso(as_of), product, lot, planned, c, seg,
             pd.Timestamp(bar_ts).isoformat(), mode))
    return order_id


def close_position(symbol: str, reason: str = "manual", as_of: datetime | None = None, price: float | None = None,
                   aid: int | None = None, confirmed: bool = True) -> OrderResult:
    """Exit an open paper position. Exits are format-checked only and never blocked by limits."""
    if not confirmed:
        raise ConfirmationRequired("Manual exits need confirmation.")
    aid = aid or account_id()
    as_of = as_of or clock.now()
    rs = db.rows("SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?", (aid, symbol))
    if not rs:
        return OrderResult(False, None, "REJECTED", f"No open paper position in {symbol}.")
    p = rs[0]
    qty = abs(p["qty"])
    side = "sell" if p["qty"] > 0 else "buy"
    ps = paper_settings()
    tick = instruments.tick_size(symbol) or 0.05
    if price is None:
        q = clock.price_at(symbol, as_of)
        if q is None:
            return OrderResult(False, None, "REJECTED", "No valid price to exit at; position left open.")
        price = costmod.slip(q["price"], side, ps["slippage_pct"], ps["slippage_ticks"], tick)
    dec = riskmod.check(riskmod.OrderRequest(symbol=symbol, side=side, qty=qty, price=price, intent="exit",
                                             segment=p["segment"], product=p["product"], lot_size=p["lot_size"],
                                             as_of=as_of, data_mode=p["data_mode"] or "SIMULATED"),
                        portfolio_state(aid, as_of))
    if not dec.passed:
        return OrderResult(False, None, "REJECTED", "; ".join(dec.blocks), dec)
    c = costmod.order_costs(side, price, qty, p["segment"], p["product"]).total
    direction = 1 if p["qty"] > 0 else -1
    gross = (price - p["avg_price"]) * qty * direction
    total_costs = c + p["entry_costs"]
    net = gross - total_costs
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO paper_orders (account_id, ts, symbol, side, qty, order_type, status, strategy, reason,
               fill_price, fill_ts, costs, product, data_mode, intent)
               VALUES (?, ?, ?, ?, ?, 'MARKET', 'FILLED', ?, ?, ?, ?, ?, ?, ?, 'exit')""",
            (aid, db.iso(as_of), symbol, side, qty, p["strategy"], reason, price, db.iso(as_of), c, p["product"], p["data_mode"]))
        conn.execute("UPDATE paper_accounts SET cash = cash + ? WHERE id = ?", (direction * price * qty - c, aid))
        conn.execute("DELETE FROM paper_positions WHERE account_id = ? AND symbol = ?", (aid, symbol))
        conn.execute(
            """INSERT INTO paper_trades (account_id, symbol, direction, qty, entry_ts, entry_price, exit_ts, exit_price,
               gross_pnl, costs, net_pnl, r_multiple, strategy, exit_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (aid, symbol, "LONG" if direction > 0 else "SHORT", qty, p["opened_ts"], p["avg_price"], db.iso(as_of), price,
             round(gross, 2), round(total_costs, 2), round(net, 2),
             round(net / p["planned_risk"], 3) if p["planned_risk"] else None, p["strategy"], reason))
    return OrderResult(True, cur.lastrowid, "FILLED", f"Closed {symbol} at {price:.2f} ({reason}). Net {net:+,.2f}.", dec, price)


def process(as_of: datetime | None = None, aid: int | None = None) -> list[str]:
    """Advance open orders and positions to the clock: fill limits, check stops, targets and flat-by."""
    aid = aid or account_id()
    as_of = as_of or clock.now()
    session = db.get_section("session", DEFAULT_SESSION)
    flat_by = parse_hhmm(session["flat_by"])
    ps = paper_settings()
    events: list[str] = []
    # pending limit entries
    for o in db.rows("SELECT * FROM paper_orders WHERE account_id = ? AND status = 'OPEN'", (aid,)):
        q = clock.price_at(o["symbol"], as_of)
        if not q:
            continue
        crossed = (q["low"] <= o["limit_price"]) if o["side"] == "buy" else (q["high"] >= o["limit_price"])
        if crossed and pd.Timestamp(q["bar_ts"]) >= pd.Timestamp(o["ts"]) - pd.Timedelta(minutes=5):
            seg, lot = _segment(o["symbol"])
            _fill_entry(aid, as_of, o["symbol"], o["side"], o["qty"], o["limit_price"], q["bar_ts"], o["stop_price"],
                        o["target_price"], o["strategy"], o["product"], seg, lot, q["mode"], "LIMIT", order_id=o["id"])
            events.append(f"Limit order {o['id']} filled: {o['side']} {o['qty']} {o['symbol']} at {o['limit_price']}")
    for p in db.rows("SELECT * FROM paper_positions WHERE account_id = ?", (aid,)):
        tf = _finest_tf(p["symbol"])
        if tf is None:
            continue
        bars = clock.bars_until(p["symbol"], tf, as_of)
        since = pd.Timestamp(p["last_checked_ts"]) if p["last_checked_ts"] else pd.Timestamp(p["opened_ts"])
        new = bars[bars["timestamp"] > since]
        direction = 1 if p["qty"] > 0 else -1
        tick = instruments.tick_size(p["symbol"]) or 0.05
        exit_side = "sell" if direction > 0 else "buy"
        closed = False
        for _, b in new.iterrows():
            bt = to_ist(b["timestamp"].to_pydatetime())
            opened_day = pd.Timestamp(p["opened_ts"]).date()
            if p["product"] == "INTRADAY" and (bt.time() >= flat_by or bt.date() != opened_day):
                px = costmod.slip(b["open"], exit_side, ps["slippage_pct"], ps["slippage_ticks"], tick)
                r = close_position(p["symbol"], "flat-by time", bt, px, aid)
                events.append(r.message)
                closed = True
                break
            stop, tgt = p["stop"], p["target"]
            if stop is not None:
                gap = (b["open"] <= stop) if direction > 0 else (b["open"] >= stop)
                touched = (b["low"] <= stop) if direction > 0 else (b["high"] >= stop)
                if gap or touched:
                    px = b["open"] if gap else stop
                    px = costmod.slip(px, exit_side, ps["slippage_pct"], ps["slippage_ticks"], tick)
                    r = close_position(p["symbol"], "stop (gap)" if gap else "stop", bt, px, aid)
                    events.append(r.message)
                    closed = True
                    break
            if tgt is not None and ((b["high"] >= tgt) if direction > 0 else (b["low"] <= tgt)):
                r = close_position(p["symbol"], "target", bt, float(tgt), aid)
                events.append(r.message)
                closed = True
                break
        if not closed and len(new):
            db.execute("UPDATE paper_positions SET last_checked_ts = ? WHERE account_id = ? AND symbol = ?",
                       (new["timestamp"].iloc[-1].isoformat(), aid, p["symbol"]))
    return events


def _finest_tf(symbol: str) -> str | None:
    return store.finest_timeframe(symbol)


def flatten_all(reason: str = "flatten all", as_of: datetime | None = None) -> list[str]:
    return [close_position(p["symbol"], reason, as_of).message for p in db.rows(
        "SELECT symbol FROM paper_positions WHERE account_id = ?", (account_id(),))]


def orders(aid: int | None = None, limit: int = 500) -> list[dict]:
    return db.rows("SELECT * FROM paper_orders WHERE account_id = ? ORDER BY id DESC LIMIT ?", (aid or account_id(), limit))


def trades(aid: int | None = None) -> list[dict]:
    return db.rows("SELECT * FROM paper_trades WHERE account_id = ? ORDER BY id DESC", (aid or account_id(),))


def cancel_order(order_id: int) -> None:
    db.execute("UPDATE paper_orders SET status = 'CANCELLED' WHERE id = ? AND status = 'OPEN'", (order_id,))


def export_csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def automation_enabled() -> bool:
    return bool(paper_settings().get("automation_enabled"))
