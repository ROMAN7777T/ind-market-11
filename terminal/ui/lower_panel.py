"""Lower information panel shared by the chart terminal."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .. import db, paper
from ..data import store
from ..news import core as news
from ..skills import risk as riskmod
from .common import fmt


def render() -> None:
    tabs = st.tabs(["🎯 Signals", "📰 News", "📌 Paper positions", "🧾 Paper orders", "🛡️ Risk monitor",
                    "🧪 Backtests", "🩺 Data quality"])
    with tabs[0]:
        res = st.session_state.get("scan_results")
        if res is None or len(res) == 0:
            st.caption("No scan yet in this session. Run one in **Strategy Scanner**.")
        else:
            cols = [c for c in ["instrument", "strategy", "classification", "setup_state", "entry_trigger", "entry_ref",
                                "stop", "target", "reward_risk", "quality", "status"] if c in res.columns]
            st.dataframe(res[cols], hide_index=True, use_container_width=True, height=260)
    with tabs[1]:
        df = news.items(limit=50)
        if df.empty:
            st.caption("No stored news. Enable a feed or import announcements in **News Intelligence**.")
        else:
            st.dataframe(df[["published_at", "headline", "publisher", "category", "relevance", "url"]], hide_index=True,
                         use_container_width=True, height=260,
                         column_config={"url": st.column_config.LinkColumn("Source link")})
    with tabs[2]:
        pos = paper.positions()
        if not pos:
            st.caption("No open paper positions.")
        else:
            st.dataframe(pd.DataFrame(pos)[["symbol", "direction", "qty", "avg_price", "last_price", "unrealized", "stop",
                                            "target", "strategy", "product", "price_ts"]], hide_index=True, use_container_width=True)
    with tabs[3]:
        o = paper.orders(limit=100)
        if not o:
            st.caption("No paper orders yet.")
        else:
            st.dataframe(pd.DataFrame(o)[["id", "ts", "symbol", "side", "qty", "order_type", "status", "fill_price", "costs",
                                          "intent", "strategy", "reason"]], hide_index=True, use_container_width=True, height=260)
    with tabs[4]:
        ps = paper.portfolio_state()
        r = riskmod.risk_settings()
        eq = ps.equity
        open_risk = sum(p["planned_risk"] or 0 for p in ps.positions)
        day_loss = -(ps.realized_today + ps.unrealized)
        lim = ps.start_of_day_equity * r["max_daily_loss_pct"] / 100
        c = st.columns(4)
        c[0].metric("Open risk", f"₹{fmt(open_risk)}", f"cap ₹{fmt(eq * r['max_open_risk_pct'] / 100)}", delta_color="off")
        c[1].metric("Today's loss", f"₹{fmt(max(0, day_loss))}", f"limit ₹{fmt(lim)}", delta_color="off")
        c[2].metric("Positions", f"{len(ps.positions)} / {r['max_positions']}")
        c[3].metric("Entries today", f"{len(ps.entries_today)} / {r['max_trades_per_day']}")
        if day_loss >= lim:
            st.error("Daily loss lockout active: new paper entries are blocked until the next session.")
        rl = db.rows("SELECT ts, symbol, strategy, decision, reasons FROM risk_log ORDER BY id DESC LIMIT 20")
        if rl:
            d = pd.DataFrame(rl)
            d["reasons"] = d["reasons"].map(lambda s: "; ".join(json.loads(s)["blocks"]) if s else "")
            st.dataframe(d, hide_index=True, use_container_width=True, height=220)
    with tabs[5]:
        bt = db.rows("SELECT id, ts, symbol, strategy, timeframe, metrics, data_mode FROM backtests ORDER BY id DESC LIMIT 30")
        if not bt:
            st.caption("No saved backtests. Run one in **Backtesting Lab**.")
        else:
            rows = []
            for b in bt:
                m = json.loads(b["metrics"] or "{}")
                rows.append({"id": b["id"], "ts": b["ts"], "symbol": b["symbol"], "strategy": b["strategy"], "tf": b["timeframe"],
                             "trades": m.get("trades"), "net": m.get("net_pnl"), "expectancy R": m.get("expectancy_r"),
                             "win %": m.get("win_rate_pct"), "max DD %": m.get("max_drawdown_pct"), "data": b["data_mode"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=260)
    with tabs[6]:
        ds = store.list_datasets()
        if not ds:
            st.caption("No datasets.")
        else:
            st.dataframe(pd.DataFrame([{"symbol": d["symbol"], "tf": d["timeframe"], "mode": d["mode"], "rows": d["rows"],
                                        "sessions": d["quality"].get("sessions"), "full sessions": d["quality"].get("full_sessions"),
                                        "missing bars": d["quality"].get("missing_bars"),
                                        "dropped invalid": d["quality"].get("invalid_ohlc"),
                                        "issues": "; ".join(d["quality"].get("issues", [])) or "none",
                                        "last bar": d["end_ts"]} for d in ds]), hide_index=True, use_container_width=True, height=260)
