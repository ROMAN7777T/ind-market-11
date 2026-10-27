import pandas as pd
import streamlit as st

from ... import ai, clock, db, paper
from ...data import instruments, store
from ...skills import alerts
from ...skills import risk as riskmod
from ..common import ask_ai_box, clock_controls, fmt, mode_banner


def _ticket(as_of) -> None:
    st.markdown("#### Paper order ticket")
    syms = [s for s in store.symbols() if (instruments.get(s) or {}).get("segment") != "IDX"]
    if not syms:
        st.info("No tradable instruments (spot indices cannot be traded).")
        return
    c = st.columns(4)
    sym = c[0].selectbox("Instrument", syms, key="pt_sym")
    side = c[1].radio("Side", ["buy", "sell"], horizontal=True, key="pt_side",
                      help="Sell = short entry (blocked unless shorts are allowed in Settings)")
    inst = instruments.get(sym) or {}
    lot = int(inst.get("lot_size") or 1)
    qty = c[2].number_input(f"Quantity (lot size {lot})", lot, 10**7, lot, lot, key="pt_qty")
    product = c[3].selectbox("Product", ["INTRADAY", "DELIVERY"], key="pt_prod")
    q = clock.price_at(sym, as_of)
    last = q["price"] if q else None
    c2 = st.columns(4)
    otype = c2[0].selectbox("Order type", ["MARKET", "LIMIT"], key="pt_type")
    limit = c2[1].number_input("Limit price", value=float(last or 0), key="pt_lim") if otype == "LIMIT" else None
    stop = c2[2].number_input("Stop-loss (required)", value=float(round((last or 0) * (0.99 if side == "buy" else 1.01), 2)), key="pt_stop")
    target = c2[3].number_input("Target", value=float(round((last or 0) * (1.02 if side == "buy" else 0.98), 2)), key="pt_tgt")
    st.caption(f"Last closed-bar price {fmt(last)} ({q['mode'] if q else 'no data'}, bar {q['bar_ts']:%d %b %H:%M})" if q else "No price at the clock time.")
    ref = limit if otype == "LIMIT" else last
    if ref:
        req = riskmod.OrderRequest(symbol=sym, side=side, qty=int(qty), price=float(ref), stop=stop or None, target=target or None,
                                   strategy="MANUAL", segment=inst.get("segment", "EQ"), product=product, lot_size=lot,
                                   as_of=as_of, data_mode=q["mode"] if q else "SIMULATED")
        dec = riskmod.check(req, paper.portfolio_state(as_of=as_of), record=False)
        (st.success if dec.passed else st.error)("Risk preview: " + ai.explain_risk({"passed": dec.passed, "blocks": dec.blocks, "warnings": dec.warnings}))
        if dec.metrics.get("trade_risk"):
            st.caption(f"Risk at the stop incl. costs ₹{fmt(dec.metrics['trade_risk'])} of ₹{fmt(dec.metrics.get('risk_budget'))} allowed.")
    cc = st.columns([2, 1])
    word = cc[0].text_input("Type CONFIRM to place this simulated order", key="pt_confirm")
    if cc[1].button("Place paper order", type="primary", disabled=word.strip() != "CONFIRM", use_container_width=True):
        r = paper.place_entry(sym, side, int(qty), stop or None, target or None, confirmed=True, product=product,
                              order_type=otype, limit_price=limit, as_of=as_of)
        if r.ok:
            st.success(r.message)
        else:
            st.error(r.message)
            if r.decision:
                st.session_state["pt_last_reject"] = {"blocks": r.decision.blocks, "warnings": r.decision.warnings}
    rej = st.session_state.get("pt_last_reject")
    if rej:
        ask_ai_box("risk rejection", {"risk_decision": rej}, ai.explain_risk({"passed": False, **rej}), "ai_rej")


def render() -> None:
    st.title("Paper Trading")
    st.markdown('<div class="iq-warn"><b>SIMULATED PORTFOLIO.</b> These are paper positions, not holdings or broker orders. '
                'The paper engine has no connection to any broker order endpoint.</div>', unsafe_allow_html=True)
    if not store.symbols():
        st.info("No data yet. Generate SIMULATED demo data on **Overview** or import CSVs in **Data Manager**.")
        return
    mode_banner()
    as_of = clock_controls("paper")
    events = paper.process(as_of)
    rung = alerts.check(as_of)
    for e in events:
        st.toast(e)
    for a in rung:
        st.toast("🔔 " + a["message"])
    e = paper.equity(as_of=as_of)
    ps = paper.portfolio_state(as_of=as_of)
    k = st.columns(5)
    k[0].metric("Equity", f"₹{fmt(e['equity'])}")
    k[1].metric("Cash", f"₹{fmt(e['cash'])}")
    k[2].metric("Unrealized", f"₹{fmt(e['unrealized'], sign=True)}")
    k[3].metric("Realized today", f"₹{fmt(ps.realized_today, sign=True)}")
    k[4].metric("Day P&L", f"₹{fmt(ps.realized_today + ps.unrealized, sign=True)}")

    tabs = st.tabs(["🧾 Ticket", "📌 Positions", "⏳ Open orders", "📜 Order history", "🔔 Alerts (skill 9)", "⚙️ Account"])
    with tabs[0]:
        _ticket(as_of)
    with tabs[1]:
        pos = e["positions"]
        if not pos:
            st.caption("No open paper positions.")
        else:
            st.dataframe(pd.DataFrame(pos)[["symbol", "direction", "qty", "avg_price", "last_price", "unrealized", "stop", "target",
                                            "planned_risk", "strategy", "product", "opened_ts", "price_ts", "data_mode"]],
                         hide_index=True, use_container_width=True)
            c = st.columns([2, 1, 1])
            sel = c[0].selectbox("Close position", [p["symbol"] for p in pos], key="pt_close_sel")
            if c[1].button("Close at market (paper)"):
                st.info(paper.close_position(sel, "manual", as_of).message)
                st.rerun()
            if c[2].button("Flatten all"):
                for m in paper.flatten_all("flatten all", as_of):
                    st.info(m)
                st.rerun()
            st.caption("Exits are never blocked by risk limits. Intraday positions close automatically at the flat-by time.")
    with tabs[2]:
        op = [o for o in paper.orders() if o["status"] == "OPEN"]
        if not op:
            st.caption("No open paper limit orders.")
        else:
            st.dataframe(pd.DataFrame(op), hide_index=True, use_container_width=True)
            cid = st.selectbox("Cancel order", [o["id"] for o in op], key="pt_cancel")
            if st.button("Cancel"):
                paper.cancel_order(cid)
                st.rerun()
    with tabs[3]:
        o = paper.orders()
        if o:
            df = pd.DataFrame(o)
            st.dataframe(df, hide_index=True, use_container_width=True, height=380)
            st.download_button("Export orders CSV", paper.export_csv(o), "paper_orders.csv")
        else:
            st.caption("No paper orders yet.")
    with tabs[4]:
        c = st.columns(4)
        asym = c[0].selectbox("Symbol", store.symbols(), key="al_sym")
        kind = c[1].selectbox("Type", list(alerts.KINDS), key="al_kind")
        lvl = c[2].number_input("Level / % move", value=0.0, key="al_lvl") if kind != "time" else None
        at = c[2].text_input("HH:MM (IST)", "15:10", key="al_at") if kind == "time" else None
        today_only = c[3].checkbox("Today only", True, key="al_today")
        if st.button("Add alert"):
            try:
                alerts.add(asym, kind, lvl, at, as_of.date().isoformat() if today_only else None)
                st.success("Alert added: it rings once.")
            except ValueError as ex:
                st.error(str(ex))
        al = alerts.list_alerts()
        if al:
            st.dataframe(pd.DataFrame(al), hide_index=True, use_container_width=True)
            d = st.selectbox("Delete alert", [a["id"] for a in al], key="al_del")
            if st.button("Delete"):
                alerts.delete(d)
                st.rerun()
        st.caption("Alerts are checked against closed bars each time this page runs or the clock moves. An alert is a fact, never an order.")
    with tabs[5]:
        s = paper.paper_settings()
        st.write(f"Initial capital ₹{fmt(e['initial_capital'])} · slippage {s['slippage_pct']}% + {s['slippage_ticks']} tick(s) per fill.")
        auto = st.toggle("Paper automation (strategy signals open paper trades without asking)", s["automation_enabled"], key="pt_auto",
                         help="Off by default. Even when on, every trade must pass the risk engine. Never touches a real broker.")
        if auto != s["automation_enabled"]:
            s["automation_enabled"] = auto
            db.set_setting("paper", s)
            st.rerun()
        if auto:
            st.warning("Paper automation is ON: triggered scanner signals will open simulated trades after passing risk checks "
                       "when you run 'Auto-trade signals' below.")
            if st.button("Auto-trade triggered signals from the last scan"):
                res = st.session_state.get("scan_results")
                if res is None or res.empty:
                    st.info("Run a scan first.")
                else:
                    trig = res[res.get("setup_state") == "TRIGGERED"] if "setup_state" in res else res.iloc[0:0]
                    for _, r in trig.iterrows():
                        from ...data import instruments as im
                        seg = (im.get(r["instrument"]) or {}).get("segment")
                        if seg == "IDX":
                            continue
                        from ...skills import sizer
                        pst = paper.portfolio_state(as_of=as_of)
                        sz = sizer.size(r["entry_ref"], r["stop"], pst.equity, pst.cash, riskmod.risk_settings(),
                                        int(r.get("direction", 1)), int((im.get(r["instrument"]) or {}).get("lot_size") or 1),
                                        seg or "EQ", "INTRADAY" if r["timeframe"] != "1d" else "DELIVERY", target=r["target"])
                        if not sz.ok:
                            st.caption(f"{r['instrument']}: sizing refused — {' '.join(sz.refusals)}")
                            continue
                        o = paper.place_entry(r["instrument"], "buy" if r.get("direction", 1) > 0 else "sell", sz.qty, r["stop"],
                                              r["target"], confirmed=True, strategy=r["strategy_id"],
                                              product="INTRADAY" if r["timeframe"] != "1d" else "DELIVERY", as_of=as_of)
                        st.caption(f"{r['instrument']}: {o.message}")
        st.divider()
        cap = st.number_input("New paper capital (₹)", 10000.0, 1e9, float(e["initial_capital"]), 10000.0, key="pt_cap")
        if st.text_input("Type RESET to start a fresh paper account (old trades are archived, not deleted)", key="pt_reset") == "RESET":
            if st.button("Reset paper account"):
                paper.reset_account(capital=cap)
                st.success("New paper account created.")
                st.rerun()
