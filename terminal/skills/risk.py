"""Skill 7 - Risk Manager: the central risk engine shared by the scanner and the paper desk.

Entries must pass every check. Exits are only format-checked and are never blocked
(getting out must always be possible). Every decision is recorded with its reasons.
These are configurable research defaults, not guarantees of safety.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .. import costs as costmod
from .. import db
from ..config import DEFAULT_RISK, DEFAULT_SESSION
from ..data import instruments
from ..timeutil import in_window


@dataclass
class OrderRequest:
    symbol: str
    side: str  # buy | sell
    qty: int
    price: float
    intent: str = "entry"  # entry | exit
    stop: float | None = None
    target: float | None = None
    strategy: str | None = None
    segment: str = "EQ"
    product: str = "INTRADAY"
    lot_size: int = 1
    as_of: datetime | None = None
    data_mode: str = "SIMULATED"
    risk_pct_override: float | None = None
    gap_pct: float | None = None
    avg_traded_value: float | None = None


@dataclass
class PortfolioState:
    equity: float
    cash: float
    start_of_day_equity: float
    positions: list[dict] = field(default_factory=list)  # symbol, qty (signed), avg_price, stop, planned_risk
    realized_today: float = 0.0
    unrealized: float = 0.0
    entries_today: list[str] = field(default_factory=list)
    risk_used_today: float = 0.0


@dataclass
class Decision:
    passed: bool
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def risk_settings() -> dict:
    return db.get_section("risk", DEFAULT_RISK)


def check(req: OrderRequest, pf: PortfolioState, risk: dict | None = None, session: dict | None = None,
          record: bool = True) -> Decision:
    risk = risk or risk_settings()
    session = session or db.get_section("session", DEFAULT_SESSION)
    d = Decision(passed=False)
    b, w, m = d.blocks, d.warnings, d.metrics

    # format (applies to entries and exits)
    if not req.symbol:
        b.append("format: no symbol")
    if req.side not in ("buy", "sell"):
        b.append("format: side must be buy or sell")
    if not isinstance(req.qty, int) or req.qty <= 0:
        b.append("format: quantity must be a positive whole number")
    if req.lot_size > 1 and req.qty % req.lot_size:
        b.append(f"format: quantity {req.qty} is not a multiple of the lot size {req.lot_size}")
    if req.price is None or req.price <= 0:
        b.append("format: no valid reference price (missing or invalid market data)")
    if req.data_mode == "LIVE_STALE":
        b.append("data: the live feed is stale; no fresh price")

    held = next((p for p in pf.positions if p["symbol"] == req.symbol), None)
    held_qty = held["qty"] if held else 0
    is_exit = req.intent == "exit"
    if is_exit:
        reduces = (req.side == "sell" and held_qty > 0 and req.qty <= held_qty) or \
                  (req.side == "buy" and held_qty < 0 and req.qty <= -held_qty)
        if not reduces:
            b.append("exit: this order does not reduce an open paper position")
        d.passed = not b
        if req.as_of and session and not in_window(req.as_of.time(), None, session["no_entries_after"]):
            w.append("after the entry cutoff: allowed because it is an exit")
        _record(req, d, record)
        return d

    # ----- entries -----
    direction = 1 if req.side == "buy" else -1
    if direction < 0 and not risk["allow_short"]:
        b.append("short: short entries are disabled in risk settings")
    if req.symbol in set(risk.get("blocked") or []):
        b.append(f"blocked: {req.symbol} is on your blocked list")
    if req.segment in ("FUT", "OPT"):
        b.extend(f"metadata: {p}" for p in instruments.fno_metadata_problems(req.symbol))
    if held:
        b.append("averaging: adding to an open position is blocked (no averaging down, no pyramiding)")
    if req.risk_pct_override is not None and req.risk_pct_override > risk["risk_per_trade_pct"]:
        b.append("martingale: requested risk above the configured per-trade risk is not allowed")

    if risk["require_stop"] and req.stop is None:
        b.append("stop: a stop-loss is required")
    risk_unit = None
    if req.stop is not None and req.price:
        risk_unit = (req.price - req.stop) * direction
        if risk_unit <= 0:
            b.append("stop: the stop is on the wrong side of the entry")
    if req.stop is not None and risk_unit and risk_unit > 0 and req.target is not None:
        rr = (req.target - req.price) * direction / risk_unit
        m["reward_risk"] = round(rr, 2)
        if rr < risk["min_reward_risk"]:
            b.append(f"reward:risk {rr:.2f} is below the minimum {risk['min_reward_risk']}")

    eq = pf.equity
    est_costs = costmod.round_trip(req.price or 0, req.stop or req.price or 0, req.qty or 0, direction,
                                   req.segment, req.product) if req.price else 0.0
    m["est_costs"] = round(est_costs, 2)
    if risk_unit and risk_unit > 0 and req.qty:
        trade_risk = req.qty * risk_unit + est_costs
        budget = eq * risk["risk_per_trade_pct"] / 100
        m.update(trade_risk=round(trade_risk, 2), risk_budget=round(budget, 2))
        if trade_risk > budget * 1.0001:
            b.append(f"loss: {req.qty} x {risk_unit:.2f} + costs {est_costs:.2f} = {trade_risk:,.2f} at the stop, "
                     f"over the {budget:,.2f} per-trade limit ({risk['risk_per_trade_pct']}% of equity)")
        open_risk = sum(max(0.0, p.get("planned_risk") or 0.0) for p in pf.positions)
        cap = eq * risk["max_open_risk_pct"] / 100
        m.update(open_risk=round(open_risk, 2), open_risk_cap=round(cap, 2))
        if open_risk + trade_risk > cap * 1.0001:
            b.append(f"aggregate risk: open risk {open_risk:,.2f} + this {trade_risk:,.2f} exceeds {cap:,.2f} "
                     f"({risk['max_open_risk_pct']}% of equity)")
        day_cap = pf.start_of_day_equity * risk["max_daily_loss_pct"] / 100
        day_loss = -(pf.realized_today + pf.unrealized)
        m.update(day_loss=round(day_loss, 2), daily_loss_limit=round(day_cap, 2))
        if day_loss >= day_cap:
            b.append(f"daily loss lockout: today's loss {day_loss:,.2f} has reached the {day_cap:,.2f} limit; "
                     "no new entries until the next session")
        else:
            worst = max(0.0, -pf.realized_today) + open_risk + trade_risk
            m["worst_case_day_loss"] = round(worst, 2)
            if worst > day_cap * 1.0001:
                b.append(f"daily loss: realized losses + open risk + this trade = {worst:,.2f} if every stop fills, "
                         f"over the {day_cap:,.2f} daily limit")

    if len(pf.positions) >= risk["max_positions"]:
        b.append(f"positions: already {len(pf.positions)} open (max {risk['max_positions']})")
    if len(pf.entries_today) >= risk["max_trades_per_day"]:
        b.append(f"trades: {len(pf.entries_today)} entries today (max {risk['max_trades_per_day']})")
    if req.symbol in pf.entries_today:
        b.append(f"duplicate: {req.symbol} was already entered today")

    notional = (req.price or 0) * (req.qty or 0)
    m["notional"] = round(notional, 2)
    if notional and notional < risk["min_order_value"]:
        b.append(f"size: order value {notional:,.0f} is below the minimum {risk['min_order_value']:,.0f}")
    if notional > eq * risk["max_position_pct"] / 100 * 1.0001:
        b.append(f"position: {notional:,.0f} is over {risk['max_position_pct']}% of equity")
    if notional > eq * risk["max_leverage"] * 1.0001:
        b.append(f"leverage: {notional:,.0f} exceeds {risk['max_leverage']}x equity")
    if direction > 0 and req.segment in ("EQ", "OPT"):
        usable = pf.cash - eq * risk["cash_buffer_pct"] / 100
        if notional + est_costs > usable:
            b.append(f"cash: needs {notional + est_costs:,.0f}, only {max(0, usable):,.0f} available after the cash buffer")

    if risk.get("enforce_entry_window", True) and req.as_of and req.product == "INTRADAY":
        t = req.as_of.time()
        if req.as_of.weekday() >= 5:
            b.append("window: market closed (weekend)")
        elif not in_window(t, session["no_entries_before"], session["no_entries_after"]):
            b.append(f"window: no new intraday entries before {session['no_entries_before']} or after {session['no_entries_after']} IST")

    # warnings (never block)
    if req.data_mode in ("SIMULATED", "HISTORICAL"):
        w.append(f"{req.data_mode} data: this is a research/paper decision, not a live market decision")
    if req.gap_pct is not None and abs(req.gap_pct) >= 2:
        w.append(f"gap: the session opened {req.gap_pct:+.1f}% from the previous close")
    if req.avg_traded_value is not None and req.avg_traded_value < 25e7:
        w.append(f"liquidity: average traded value Rs {req.avg_traded_value / 1e7:,.1f} cr is below Rs 25 cr")
    if risk_unit and risk_unit > 0 and req.qty and est_costs > 0.1 * req.qty * risk_unit:
        w.append(f"costs: estimated costs are {est_costs / (req.qty * risk_unit) * 100:.0f}% of the risk")
    if req.segment in ("FUT", "OPT"):
        inst = instruments.get(req.symbol)
        if inst and inst.get("expiry") and req.as_of:
            try:
                dte = (datetime.fromisoformat(inst["expiry"]).date() - req.as_of.date()).days
                if dte <= 2:
                    w.append(f"expiry: {dte} day(s) to expiry; expiry-day moves and liquidity can be extreme")
            except ValueError:
                w.append("expiry: unreadable expiry date in instrument metadata")
    w.append("slippage: stops are orders, not guarantees; gaps can fill beyond them")

    d.passed = not b
    _record(req, d, record)
    return d


def _record(req: OrderRequest, d: Decision, record: bool) -> None:
    if not record:
        return
    details = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(req).items()}
    details["metrics"] = d.metrics
    db.execute("INSERT INTO risk_log (ts, symbol, strategy, decision, reasons, details) VALUES (?, ?, ?, ?, ?, ?)",
               (db.now_str(), req.symbol, req.strategy, "PASS" if d.passed else "BLOCK",
                json.dumps({"blocks": d.blocks, "warnings": d.warnings}), json.dumps(details, default=str)))
