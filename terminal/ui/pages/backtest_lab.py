import json
from dataclasses import asdict

import pandas as pd
import plotly.express as px
import streamlit as st

from ... import ai, backtest, costs, db
from ...data import instruments, store
from ...strategies import registry
from ..charts import equity_figure, style
from ..common import ask_ai_box, fmt, mode_banner


def render() -> None:
    st.title("Backtesting Lab")
    syms = store.symbols()
    if not syms:
        st.info("No data yet. Generate SIMULATED demo data on **Overview** or import CSVs in **Data Manager**.")
        return
    strategies = [s for s in registry.all_strategies() if s.meta.trade_capable]
    c = st.columns(4)
    sym = c[0].selectbox("Instrument", syms, key="bt_sym")
    sid = c[1].selectbox("Strategy", [s.meta.id for s in strategies], format_func=lambda i: registry.get(i).meta.name, key="bt_strat")
    strat = registry.get(sid)
    tfs = [t for t in strat.meta.timeframes if t in store.timeframes_for(sym)]
    if not tfs:
        st.warning(f"{strat.meta.name} needs {', '.join(strat.meta.timeframes)} data for {sym}.")
        return
    tf = c[2].selectbox("Timeframe", tfs, key="bt_tf")
    inst = instruments.get(sym) or {}
    seg = inst.get("segment", "EQ")
    if seg == "IDX":
        st.warning("Spot indices are not tradable: results are illustrative only (no lot size, no traded instrument). "
                   "Backtest the index future instead.")
    if seg == "OPT":
        st.info("Option backtests use this contract's own stored historical prices.")
    df = store.load(sym, tf)
    dates = df["timestamp"].dt.date
    rng = c[3].date_input("Date range", (dates.min(), dates.max()), min_value=dates.min(), max_value=dates.max(), key="bt_rng")
    mode_banner(sym)

    with st.expander("Parameters, sizing, costs and risk", expanded=True):
        cfg = registry.settings(sid)["params"]
        params = {}
        if strat.meta.params:
            pc = st.columns(min(4, len(strat.meta.params)))
            for j, p in enumerate(strat.meta.params):
                col = pc[j % len(pc)]
                cur = cfg[p.name]
                if p.options:
                    params[p.name] = col.selectbox(p.label, p.options, index=p.options.index(cur), key=f"bt_{p.name}")
                elif isinstance(p.default, bool):
                    params[p.name] = col.checkbox(p.label, bool(cur), key=f"bt_{p.name}")
                elif isinstance(p.default, int):
                    params[p.name] = int(col.number_input(p.label, int(p.min), int(p.max), int(cur), int(p.step or 1), key=f"bt_{p.name}"))
                else:
                    params[p.name] = float(col.number_input(p.label, float(p.min), float(p.max), float(cur), float(p.step or 0.1), key=f"bt_{p.name}"))
        s1 = st.columns(4)
        capital = s1[0].number_input("Initial capital (₹)", 10000.0, 1e9, 100000.0, 10000.0, key="bt_cap")
        sizing = s1[1].selectbox("Position sizing", ["risk_pct", "fixed_qty", "fixed_value"], key="bt_sizing",
                                 format_func=lambda s: {"risk_pct": "% of equity at risk", "fixed_qty": "Fixed lots/shares",
                                                        "fixed_value": "Fixed ₹ value"}[s])
        risk_pct = s1[2].number_input("Risk per trade %", 0.05, 5.0, 0.5, 0.05, key="bt_risk")
        lev = s1[3].number_input("Max leverage (x)", 0.1, 5.0, 1.0, 0.1, key="bt_lev")
        s2 = st.columns(4)
        fq = s2[0].number_input("Fixed qty (lots)", 1, 10000, 1, key="bt_fq")
        fv = s2[1].number_input("Fixed value (₹)", 1000.0, 1e8, 20000.0, 1000.0, key="bt_fv")
        product = s2[2].selectbox("Product", ["INTRADAY", "DELIVERY"], index=0 if "intraday" in strat.meta.styles and tf != "1d" else 1, key="bt_prod")
        oos = s2[3].slider("Out-of-sample share", 0.0, 0.6, 0.3, 0.05, key="bt_oos")
        s3 = st.columns(4)
        slip = s3[0].number_input("Slippage % per fill", 0.0, 1.0, 0.03, 0.01, key="bt_slip")
        ticks = s3[1].number_input("Slippage ticks per fill", 0, 20, 1, key="bt_ticks")
        allow_short = s3[2].checkbox("Allow shorts (if the strategy has a short side)", False, key="bt_short")
        model = costs.load_model()
        s3[3].caption(f"Cost model: config/cost_model.json — *{model['as_of']}*")

    lo, hi = (rng if isinstance(rng, tuple) and len(rng) == 2 else (dates.min(), dates.max()))
    data = df[(dates >= lo) & (dates <= hi)].reset_index(drop=True)
    settings = backtest.BTSettings(
        timeframe=tf, session=store.session_settings(), initial_capital=capital, sizing=sizing, risk_pct=risk_pct,
        fixed_qty=int(fq), fixed_value=fv, max_leverage=lev, segment=seg if seg in ("FUT", "OPT") else "EQ",
        product=product, lot_size=int(inst.get("lot_size") or 1), tick=float(inst.get("tick_size") or 0.05),
        slippage_pct=slip, slippage_ticks=int(ticks), oos_fraction=oos, allow_short=allow_short)
    b = st.columns([1, 1, 3])
    run = b[0].button("Run backtest", type="primary")
    wf = b[1].button("Walk-forward")
    if run:
        with st.spinner("Running…"):
            try:
                st.session_state["bt_result"] = (backtest.run(data, strat, params, settings), sym, sid, tf, params, settings)
            except ValueError as e:
                st.error(str(e))
    if wf:
        with st.spinner("Walk-forward: choosing parameters on past data only, testing on the next fold…"):
            st.session_state["bt_wf"] = backtest.walk_forward(data, strat, params, settings, folds=4)

    res = st.session_state.get("bt_result")
    if res and res[1] == sym and res[2] == sid:
        r, _, _, _, p_used, s_used = res
        m = r.metrics
        k = st.columns(6)
        k[0].metric("Net P&L", f"₹{fmt(m.get('net_pnl'))}", f"{fmt(m.get('return_pct'), 2, True, True)}")
        k[1].metric("Trades", m.get("trades"))
        k[2].metric("Win rate", fmt(m.get("win_rate_pct"), 1, True))
        k[3].metric("Profit factor", fmt(m.get("profit_factor")))
        k[4].metric("Expectancy", f"₹{fmt(m.get('expectancy'))}", f"{fmt(m.get('expectancy_r'), 3)} R", delta_color="off")
        k[5].metric("Max drawdown", fmt(m.get("max_drawdown_pct"), 2, True))
        k2 = st.columns(6)
        k2[0].metric("Avg win", f"₹{fmt(m.get('avg_win'))}")
        k2[1].metric("Avg loss", f"₹{fmt(m.get('avg_loss'))}")
        k2[2].metric("Costs paid", f"₹{fmt(m.get('total_costs'))}")
        k2[3].metric("Avg holding", m.get("avg_hold", "—"))
        k2[4].metric("Exposure", fmt(m.get("exposure_pct"), 1, True))
        k2[5].metric("Gross P&L", f"₹{fmt(m.get('gross_pnl'))}")
        if m.get("warning"):
            st.warning(m["warning"])
        if m.get("trades"):
            st.plotly_chart(equity_figure(r.equity, f"{sym} · {strat.meta.name} · {tf}"), use_container_width=True)
            t = st.columns(2)
            t[0].markdown("**In-sample vs out-of-sample**")
            t[0].dataframe(pd.DataFrame([{"sample": "In-sample", **{x: r.metrics_is.get(x) for x in ("trades", "net_pnl", "win_rate_pct", "expectancy_r", "profit_factor")}},
                                         {"sample": "Out-of-sample", **{x: r.metrics_oos.get(x) for x in ("trades", "net_pnl", "win_rate_pct", "expectancy_r", "profit_factor")}}]),
                           hide_index=True, use_container_width=True)
            t[0].markdown("**Exit reasons**")
            t[0].json(m.get("exit_reasons", {}))
            fig = px.histogram(r.trades, x="r_multiple", nbins=30)
            t[1].plotly_chart(style(fig, 280, "R-multiple distribution (after costs)"), use_container_width=True)
            st.markdown("**Trade ledger**")
            st.dataframe(r.trades, hide_index=True, use_container_width=True, height=300)
            st.download_button("Export ledger CSV", r.trades.to_csv(index=False).encode(), f"backtest_{sym}_{sid}_{tf}.csv")
        st.caption(" · ".join(r.notes) + f" · Skipped signals: {r.skipped}.")
        st.markdown('<div class="iq-warn">Backtests describe the past on this dataset only. They are not proof of future '
                    'profitability. Survivorship and completeness of imported data are not verified by the terminal.</div>',
                    unsafe_allow_html=True)
        if st.button("Save summary"):
            db.execute("INSERT INTO backtests (ts, symbol, strategy, timeframe, params, settings, metrics, data_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (db.now_str(), sym, sid, tf, json.dumps(p_used), json.dumps({k: v for k, v in asdict(s_used).items() if k != "cost_model"}),
                        json.dumps(m, default=str), store.symbol_mode(sym).value))
            st.success("Saved to the local database.")
        ask_ai_box("backtest", {"metrics": m, "in_sample": r.metrics_is, "out_of_sample": r.metrics_oos, "strategy": strat.meta.name},
                   ai.explain_backtest(m, r.metrics_is, r.metrics_oos), "ai_bt")
    wfr = st.session_state.get("bt_wf")
    if wfr is not None:
        st.markdown("**Walk-forward results** (parameters chosen on prior data only, from the strategy's small grid)")
        if wfr.empty:
            st.info("Not enough data for walk-forward folds.")
        else:
            st.dataframe(wfr, hide_index=True, use_container_width=True)
