"""Indian transaction costs and slippage.

Defaults live in config/cost_model.json and are explicitly unverified: rates change and
differ by broker. Every backtest and paper fill uses this one model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .config import config_dir


def load_model() -> dict:
    with open(config_dir() / "cost_model.json", encoding="utf-8") as f:
        return json.load(f)


def segment_key(segment: str, product: str) -> str:
    if segment in ("FUT", "OPT"):
        return segment
    return "EQ_DELIVERY" if product == "DELIVERY" else "EQ_INTRADAY"


@dataclass
class CostBreakdown:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst

    def as_dict(self) -> dict:
        d = {k: round(v, 2) for k, v in self.__dict__.items()}
        d["total"] = round(self.total, 2)
        return d


def order_costs(side: str, price: float, qty: float, segment: str = "EQ", product: str = "INTRADAY",
                model: dict | None = None) -> CostBreakdown:
    """Costs for one order leg. `price` is the premium for options, `qty` is units (lots x lot size)."""
    model = model or load_model()
    seg = model["segments"][segment_key(segment, product)]
    turnover = abs(price * qty)
    if seg.get("brokerage_flat_per_order") is not None:
        brokerage = float(seg["brokerage_flat_per_order"])
    else:
        brokerage = turnover * (seg.get("brokerage_pct") or 0) / 100
        cap = seg.get("brokerage_max_per_order")
        if cap is not None:
            brokerage = min(brokerage, cap)
    if turnover == 0:
        brokerage = 0.0
    stt_pct = seg["stt_buy_pct"] if side == "buy" else seg["stt_sell_pct"]
    stt = turnover * stt_pct / 100
    exchange = turnover * seg["exchange_txn_pct"] / 100
    sebi = turnover * model["sebi_fee_per_crore"] / 1e7
    stamp = turnover * seg["stamp_buy_pct"] / 100 if side == "buy" else 0.0
    gst = (brokerage + exchange + sebi) * model["gst_pct"] / 100
    return CostBreakdown(brokerage, stt, exchange, sebi, stamp, gst)


def round_trip(price_in: float, price_out: float, qty: float, direction: int = 1, segment: str = "EQ",
               product: str = "INTRADAY", model: dict | None = None) -> float:
    model = model or load_model()
    first, second = ("buy", "sell") if direction > 0 else ("sell", "buy")
    return (order_costs(first, price_in, qty, segment, product, model).total
            + order_costs(second, price_out, qty, segment, product, model).total)


def slip(price: float, side: str, slippage_pct: float, ticks: int = 0, tick: float = 0.05) -> float:
    """Adverse slippage: buys fill higher, sells lower, rounded adversely onto the tick grid."""
    import math

    adj = price * slippage_pct / 100 + ticks * tick
    raw = price + adj if side == "buy" else price - adj
    if not tick or tick <= 0:
        return raw
    q = raw / tick
    q = math.ceil(q - 1e-9) if side == "buy" else math.floor(q + 1e-9)
    return round(q * tick, 4)
