import pandas as pd
import streamlit as st

from ... import clock, db, paper
from ...data import simulated, store
from ...providers.manager import provider_manager
from ...skills import SKILLS
from ...strategies import registry
from ..common import add_to_watchlist, fmt, mode_banner


def first_run_panel() -> None:
    st.markdown("### Welcome — no market data yet")
    st.write("The terminal works fully offline. Choose how to start:")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("**Generate SIMULATED demo data**")
        st.caption("12 synthetic instruments with a SIM_ prefix (indices, futures, stocks), 260 sessions of 5-minute bars. "
                   "Synthetic prices only: they do not represent any real instrument.")
        if st.button("Generate simulated data", type="primary"):
            with st.spinner("Generating synthetic candles…"):
                made = simulated.generate_all()
                wid = db.rows("SELECT id FROM watchlists ORDER BY id LIMIT 1")[0]["id"]
                for s in made[:8]:
                    add_to_watchlist(wid, s)
            st.success(f"Created {len(made)} SIMULATED instruments.")
            st.rerun()
    with c2.container(border=True):
        st.markdown("**Import your own historical CSV**")
        st.caption("Columns: timestamp, open, high, low, close, volume (IST). Data Manager validates every candle.")
        st.info("Open **Data Manager** in the sidebar to import files.")


def render() -> None:
    st.title("Overview")
    if not store.symbols():
        first_run_panel()
    mode_banner()
    as_of = clock.now()
    paper.process(as_of)
    e = paper.equity(as_of=as_of)
    ps = paper.portfolio_state(as_of=as_of)
    c = st.columns(6)
    c[0].metric("Paper equity", f"₹{fmt(e['equity'])}", f"{fmt(e['equity'] - e['initial_capital'], 2, sign=True)} total")
    c[1].metric("Cash", f"₹{fmt(e['cash'])}")
    c[2].metric("Open positions", len(e["positions"]))
    c[3].metric("Today's realized", f"₹{fmt(ps.realized_today, sign=True)}")
    c[4].metric("Kotak", provider_manager().kotak.info.status.value)
    c[5].metric("Datasets", len(store.list_datasets()))

    left, right = st.columns([1.15, 1])
    with left:
        st.subheader("The 11 skill modules")
        st.caption("From the Cloud9 Markets / day-trader-skill reference, adapted for NSE. Details: docs/strategy_specification.md")
        st.dataframe(pd.DataFrame([{"#": n, "Skill": name, "What it does here": desc} for n, name, _, desc in SKILLS]),
                     hide_index=True, use_container_width=True, height=422)
    with right:
        st.subheader("Strategies")
        rows = []
        for s in registry.all_strategies():
            cfg = registry.settings(s.meta.id)
            rows.append({"Strategy": s.meta.name, "Source": "11-skill reference" if s.meta.group == "REFERENCE" else "Master prompt",
                         "Style": ", ".join(s.meta.styles), "Enabled": "✅" if cfg["enabled"] else "—",
                         "Trades": "yes" if s.meta.trade_capable else "tag only", "Tested": "no"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=422)
    st.subheader("Recent risk decisions")
    rl = db.rows("SELECT ts, symbol, strategy, decision, reasons FROM risk_log ORDER BY id DESC LIMIT 8")
    if rl:
        st.dataframe(pd.DataFrame(rl), hide_index=True, use_container_width=True)
    else:
        st.caption("No paper orders checked yet.")
    st.caption("Nothing on this terminal is financial advice. Strategy matches are rule matches, not predictions. "
               "All trading is simulated; no order can reach a broker.")
