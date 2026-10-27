import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import time as dtime

from ... import ai, clock, costs, paper
from ... import indicators as ind
from ...data import instruments, store
from ...skills import alerts, entry_timer, exit_planner, scanner, sizer, time_machine
from ...skills import risk as riskmod
from ...strategies import registry
from ..charts import style
from ..common import ask_ai_box, clock_controls, fmt, mode_banner


def _scan_tab(as_of) -> None:
    strategies = registry.all_strategies()
    enabled = [s.meta.id for s in registry.enabled()]
    c = st.columns([2.4, 1.4, 0.8])
    pick = c[0].multiselect("Strategies", [s.meta.id for s in strategies], default=enabled,
                            format_func=lambda i: registry.get(i).meta.name, key="sc_strats")
    syms = c[1].multiselect("Instruments (empty = all)", store.symbols(), key="sc_syms")
    idle = c[2].toggle("Show idle", False, key="sc_idle", help="Also list instruments with no setup on the latest bar")
    if st.button("Run scan", type="primary"):
        with st.spinner("Scanning closed bars at the clock time…"):
            st.session_state["scan_results"] = scanner.run(syms or None, pick or None, as_of, include_idle=idle)
            st.session_state["scan_as_of"] = as_of
    res = st.session_state.get("scan_results")
    if res is None:
        st.caption("Press **Run scan**. A match means a chart met a rule; it is not a buy and not a prediction.")
        return
    st.caption(f"Scanned at clock {st.session_state['scan_as_of']:%d %b %Y %H:%M} IST · {len(res)} rows · "
               "Signals on SIMULATED or HISTORICAL data are never live signals.")
    if res.empty:
        st.info("No instrument matched any selected rule at this clock time.")
        return
    cls = st.multiselect("Classification", ["BULLISH", "BEARISH", "NEUTRAL", "NO-TRADE"], key="sc_cls")
    view = res[res["classification"].isin(cls)] if cls else res
    cols = [c for c in ["instrument", "strategy", "timeframe", "classification", "setup_state", "entry_trigger", "entry_ref",
                        "stop", "target", "reward_risk", "quality", "data_timestamp", "status"] if c in view.columns]
    st.dataframe(view[cols], hide_index=True, use_container_width=True, height=330,
                 column_config={"quality": st.column_config.ProgressColumn("Quality", min_value=0, max_value=100, format="%d")})
    if len(view):
        i = st.selectbox("Details for row", view.index, format_func=lambda k: f"{view.loc[k, 'instrument']} · {view.loc[k, 'strategy']}",
                         key="sc_row")
        row = view.loc[i].to_dict()
        row = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in row.items()}
        a, b = st.columns([1.2, 1])
        with a:
            st.markdown(ai.explain_signal(row))
        with b:
            st.markdown("**Supporting indicators**")
            st.json(row.get("indicators") or {}, expanded=True)
            if row.get("quality_parts"):
                st.markdown("**Quality score breakdown**")
                st.json(row["quality_parts"], expanded=True)
            if row.get("setup_state") == "TRIGGERED" and st.button("Send to Trade Desk →"):
                st.session_state["td_prefill"] = row
                st.info("Prefilled: open the **Trade Desk** tab.")
        ask_ai_box("signal", {"signal": row}, "Rules-based summary shown above.", "ai_sig")


def _daily_tab(as_of) -> None:
    st.markdown("Reference **skill 1** pre-market scan: five tags on daily closes (closes before the clock date).")
    df = scanner.daily_tags(as_of=as_of)
    if df.empty:
        st.info("Needs at least 25 daily bars per instrument.")
        return
    only = st.toggle("Only instruments with at least one tag", True, key="dt_only")
    tags = ["breakout_20d", "bull_flag", "reclaim_ma20", "oversold", "oversold_bounce"]
    if only:
        df = df[df[tags].any(axis=1)]
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={t: st.column_config.CheckboxColumn(t) for t in tags})
    st.caption("Tags are watchlist candidates. In the reference they had no exits; the proposed swing exits are in the "
               "strategy library and are disabled by default until backtested.")


def _desk_tab(as_of) -> None:
    st.markdown("Skills **3 → 4 → 5 → 6 → 7 → 8**: entry timer, exit plan, Time Machine, sizing, risk check, paper order.")
    pre = st.session_state.get("td_prefill") or {}
    syms = [s for s in store.symbols() if "5m" in store.timeframes_for(s)]
    if not syms:
        st.info("Needs 5-minute data.")
        return
    c = st.columns(4)
    sym = c[0].selectbox("Instrument", syms, index=syms.index(pre["instrument"]) if pre.get("instrument") in syms else 0, key="td_sym")
    setup = c[1].selectbox("Setup", ["orb", "level"], key="td_setup", format_func=lambda s: {"orb": "Opening-range breakout", "level": "Close above a level"}[s])
    orm = c[2].number_input("Opening range (min)", 5, 60, 15, 5, key="td_orm")
    volx = c[3].number_input("Min volume x range avg", 0.0, 5.0, 0.0, 0.25, key="td_vx")
    level = st.number_input("Level", value=0.0, key="td_lvl") if setup == "level" else None
    sess = store.session_settings()
    bars = clock.bars_until(sym, "5m", as_of)
    stt = entry_timer.status(bars, "5m", as_of, sess, setup, int(orm), level or None, volx)
    colour = {"TRIGGERED": "success", "WAITING": "info", "EXPIRED": "warning"}.get(stt["state"], "warning")
    getattr(st, colour)(f"**Entry timer: {stt['state']}** — {stt['message']}")
    if stt["state"] != "TRIGGERED":
        st.caption("Advance the replay clock to watch the setup bar by bar.")
        return

    st.markdown("#### Exit plan (skill 4)")
    e = st.columns(4)
    rule = e[0].selectbox("Stop rule", ["or_mid", "or_low", "atr", "pct", "price"], key="td_rule",
                          format_func=lambda r: {"or_mid": "OR midpoint (default)", "or_low": "OR low", "atr": "ATR x K",
                                                 "pct": "Percent", "price": "Price"}[r])
    tgt = e[1].selectbox("Target", ["2R", "1.5R", "1R", "3R"], key="td_tgt")
    k = e[2].number_input("ATR K / percent / price", value=1.5, key="td_k")
    product = e[3].selectbox("Product", ["INTRADAY", "DELIVERY"], key="td_prod")
    inst = instruments.get(sym) or {}
    tick = float(inst.get("tick_size") or 0.05)
    seg = inst.get("segment", "EQ")
    entry = stt["trigger_price"]
    atr_v = float(ind.atr(bars, 14).iloc[-1]) if len(bars) > 14 else None
    est_cost_unit = costs.round_trip(entry, entry, 1, 1, "FUT" if seg == "FUT" else "EQ", product) if seg != "IDX" else 0
    tt = dtime(*map(int, stt["trigger_time"].split(":")))
    plan = exit_planner.plan(entry, 1, rule, tgt, tick, stt.get("or_high"), stt.get("or_low"), atr_v, k,
                             stop_price=k if rule == "price" else None, stop_pct=k if rule == "pct" else None,
                             est_cost_per_unit=est_cost_unit, flat_by=sess["flat_by"] if product == "INTRADAY" else None,
                             entry_time=tt)
    if not plan.ok:
        st.error("Exit plan refused: " + " ".join(plan.refusals))
        return
    m = st.columns(5)
    m[0].metric("Entry", fmt(plan.entry))
    m[1].metric("Stop", fmt(plan.stop))
    m[2].metric("Target", fmt(plan.target))
    m[3].metric("Risk / unit", fmt(plan.risk_per_unit))
    m[4].metric("Reward:risk", fmt(plan.reward_risk))
    st.caption(" · ".join(plan.notes) + (f" · Flat by {plan.flat_by} IST." if plan.flat_by else ""))

    st.markdown("#### Time Machine (skill 5)")
    tmc = st.columns([1, 1, 2])
    n = tmc[0].select_slider("Replays", [1000, 5000, 10000], 10000, key="tm_n")
    seed = tmc[1].number_input("Seed", 0, 10**6, 19, key="tm_seed")
    if tmc[2].button("Run the Time Machine"):
        bar_start = pd.Timestamp(f"{as_of.date()} {stt['bar_start']}").tz_localize(as_of.tzinfo)
        with st.spinner("Replaying the rest of the session…"):
            r = time_machine.run(store.load(sym, "5m"), {"entry_bar_ts": bar_start, "entry": plan.entry, "stop": plan.stop,
                                                         "target": plan.target, "direction": 1, "setup": setup,
                                                         "or_minutes": int(orm), "stop_rule": rule,
                                                         "target_r": float(tgt[:-1])}, sess, n=int(n), seed=int(seed),
                                 cost_per_unit=est_cost_unit)
        st.session_state["tm_result"] = r
    r = st.session_state.get("tm_result")
    if r:
        if not r["ok"]:
            st.warning(r["message"])
        else:
            mm = st.columns(5)
            mm[0].metric("Target first", f"{r['target_first_pct']}%")
            mm[1].metric("Stop first", f"{r['stop_first_pct']}%")
            mm[2].metric("Neither", f"{r['neither_pct']}%")
            mm[3].metric("Green", f"{r['green_pct']}%")
            mm[4].metric("Avg R (after costs)", f"{r['avg_r']:+.3f}")
            st.markdown(f"**{r['verdict']}**")
            for x in r["extra"]:
                st.caption(x)
            h = r.get("history")
            if h:
                st.caption(f"History: the same rule on {h['sessions']} past sessions fired {h['fired']} times: {h['target']} target, "
                           f"{h['stop']} stop, {h['neither']} neither; average R {h['avg_r']}.")
            st.caption(f"{r['replays']:,} replays, seed {r['seed']}, pool {r['sessions_in_pool']} full sessions, "
                       f"close median {fmt(r['close_median'])} (5–95%: {fmt(r['close_p5'])}–{fmt(r['close_p95'])}). "
                       "Built from past sessions only: a simulation, not a forecast.")
            fan = r["fan"]
            fig = go.Figure()
            xs = list(range(1, len(fan[50]) + 1))
            fig.add_trace(go.Scatter(x=xs, y=fan[95], line=dict(width=0), showlegend=False))
            fig.add_trace(go.Scatter(x=xs, y=fan[5], fill="tonexty", fillcolor="rgba(88,166,255,0.15)", line=dict(width=0), name="5–95%"))
            fig.add_trace(go.Scatter(x=xs, y=fan[50], line=dict(color="#58a6ff"), name="Median"))
            fig.add_hline(y=plan.stop, line=dict(color="#ef5350", dash="dash"), annotation_text="Stop")
            fig.add_hline(y=plan.target, line=dict(color="#26a69a", dash="dash"), annotation_text="Target")
            st.plotly_chart(style(fig, 280, "Replay fan (bars after entry)"), use_container_width=True)

    st.markdown("#### Size and risk check (skills 6 and 7)")
    ps = paper.portfolio_state(as_of=as_of)
    rs = riskmod.risk_settings()
    if seg == "IDX":
        st.warning("Spot indices cannot be traded: use the index future (e.g. SIM_NIFTY_FUT) or options.")
        return
    sz = sizer.size(plan.entry, plan.stop, ps.equity, ps.cash, rs, 1, int(inst.get("lot_size") or 1),
                    seg, product, fresh_price=(clock.price_at(sym, as_of) or {}).get("price"), target=plan.target)
    if not sz.ok:
        st.error("Sizing refused: " + " ".join(sz.refusals))
        return
    st.dataframe(pd.DataFrame([{"limit": k, "units": v["units"], "lots": v["lots"], "decides": "◀" if k == sz.deciding_limit else ""}
                               for k, v in sz.limits.items()]), hide_index=True, use_container_width=True)
    st.markdown(f"**{sz.qty} units** ({sz.lots} lot(s)) at ~{fmt(sz.sized_at)} = ₹{fmt(sz.notional)}; bound by **{sz.deciding_limit}**. "
                f"Max loss at the stop incl. est. costs ₹{fmt(sz.max_loss)} (costs ₹{fmt(sz.est_costs)}).")
    req = riskmod.OrderRequest(symbol=sym, side="buy", qty=sz.qty, price=sz.sized_at, stop=plan.stop, target=plan.target,
                               strategy="REF_ORB" if setup == "orb" else "LEVEL", segment=seg, product=product,
                               lot_size=int(inst.get("lot_size") or 1), as_of=as_of, data_mode=store.symbol_mode(sym).value)
    dec = riskmod.check(req, ps, rs, sess, record=False)
    (st.success if dec.passed else st.error)(ai.explain_risk({"passed": dec.passed, "blocks": dec.blocks, "warnings": dec.warnings}))
    if not dec.passed:
        return

    st.markdown("#### Paper order (skill 8)")
    st.caption("Simulated only. Type CONFIRM to place this paper order; nothing is sent to any broker.")
    cc = st.columns([2, 1, 1])
    word = cc[0].text_input("Type CONFIRM", key="td_confirm")
    add_alerts = cc[1].checkbox("Add plan alerts (skill 9)", True, key="td_alerts")
    if cc[2].button("Place paper order", type="primary", disabled=word.strip() != "CONFIRM"):
        res = paper.place_entry(sym, "buy", sz.qty, plan.stop, plan.target, confirmed=True, strategy=req.strategy,
                                product=product, as_of=as_of)
        (st.success if res.ok else st.error)(res.message)
        if res.ok and add_alerts and plan.flat_by:
            alerts.add_from_plan(sym, plan.stop, plan.target, plan.flat_by, as_of.date().isoformat())
            st.caption("Stop, target and flat-by alerts added.")


def _library_tab() -> None:
    for s in registry.all_strategies():
        m = s.meta
        cfg = registry.settings(m.id)
        badge = "11-skill reference" if m.group == "REFERENCE" else "Master prompt (not in reference)"
        with st.expander(f"{'✅' if cfg['enabled'] else '⏸️'} {m.name} — {badge} · {', '.join(m.styles)} · {', '.join(m.timeframes)}"):
            st.markdown(f"_{m.summary}_")
            if not m.tested:
                st.markdown('<div class="iq-warn">Not yet validated by backtesting on Indian market data.</div>', unsafe_allow_html=True)
            st.markdown("\n".join(f"- **{k.replace('_', ' ').title()}**: {v}" for k, v in m.rules.items()))
            a, b = st.columns(2)
            a.markdown("**Original rules (reference)**\n" + "\n".join(f"- {x}" for x in m.original))
            b.markdown("**Indian-market adaptations**\n" + ("\n".join(f"- {x}" for x in m.adaptations) or "- none"))
            en = st.toggle("Enabled in scanner", cfg["enabled"], key=f"lib_en_{m.id}")
            newp = {}
            if m.params:
                cols = st.columns(min(4, len(m.params)))
                for j, p in enumerate(m.params):
                    col = cols[j % len(cols)]
                    cur = cfg["params"][p.name]
                    if p.options:
                        newp[p.name] = col.selectbox(p.label, p.options, index=p.options.index(cur), key=f"lib_{m.id}_{p.name}")
                    elif isinstance(p.default, bool):
                        newp[p.name] = col.checkbox(p.label, bool(cur), key=f"lib_{m.id}_{p.name}")
                    elif isinstance(p.default, int):
                        newp[p.name] = int(col.number_input(p.label, int(p.min), int(p.max), int(cur), int(p.step or 1), key=f"lib_{m.id}_{p.name}"))
                    else:
                        newp[p.name] = float(col.number_input(p.label, float(p.min), float(p.max), float(cur), float(p.step or 0.1), key=f"lib_{m.id}_{p.name}"))
            if st.button("Save", key=f"lib_save_{m.id}"):
                registry.save(m.id, en, newp)
                st.success("Saved.")


def render() -> None:
    st.title("Strategy Scanner")
    if not store.symbols():
        st.info("No data yet. Generate SIMULATED demo data on **Overview** or import CSVs in **Data Manager**.")
        return
    mode_banner()
    as_of = clock_controls("scan")
    tabs = st.tabs(["🎯 Scan results", "📅 Daily setups (skill 1)", "🧭 Trade Desk (skills 3–8)", "📚 Strategy library & settings"])
    with tabs[0]:
        _scan_tab(as_of)
    with tabs[1]:
        _daily_tab(as_of)
    with tabs[2]:
        _desk_tab(as_of)
    with tabs[3]:
        _library_tab()
