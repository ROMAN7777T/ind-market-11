from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ... import clock, fno
from ...data import instruments, store
from ...data.modes import DataMode
from ..charts import style
from ..common import fmt


def _chain_section(as_of) -> None:
    chains = fno.chains()
    with st.expander("Add an option chain"):
        st.caption("Import a chain snapshot exported from your data source: strike, option_type (CE/PE), ltp, bid, ask, oi, "
                   "oi_change, volume, iv (optional, %). Expiry and lot size must come from verified contract metadata.")
        c = st.columns(4)
        und = c[0].text_input("Underlying", key="oc_und").upper()
        exp = c[1].date_input("Expiry", key="oc_exp")
        snap = c[2].text_input("Snapshot time (ISO, IST)", as_of.strftime("%Y-%m-%dT%H:%M"), key="oc_asof")
        up = c[3].file_uploader("Chain CSV", type=["csv"], key="oc_up")
        if up and und and st.button("Import chain"):
            try:
                fno.save_chain(und, exp.isoformat(), snap, pd.read_csv(up), "CSV import", DataMode.HISTORICAL)
                st.success("Imported.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
        st.divider()
        sims = [s for s in store.symbols() if s in ("SIM_NIFTY", "SIM_BANKNIFTY")]
        if sims:
            s = st.selectbox("Or generate a SIMULATED chain for", sims, key="oc_sim")
            if st.button("Generate SIMULATED chain"):
                q = clock.price_at(s, as_of)
                if not q:
                    st.error("No price at the clock time.")
                else:
                    step = 50 if s == "SIM_NIFTY" else 100
                    expiry, df = fno.simulate_chain(s, q["price"], as_of, step)
                    fno.save_chain(s, expiry, as_of.strftime("%Y-%m-%dT%H:%M"), df, "Generated (SIMULATED)", DataMode.SIMULATED)
                    st.rerun()
    if not chains:
        st.info("No option chains stored. Import one above (or generate a SIMULATED chain for demonstration). "
                "Option analytics are disabled until contract data exists; index candles are never used as option prices.")
        return
    labels = [f"{c['underlying']} · exp {c['expiry']} · snapshot {c['as_of']} · {c['mode']}" for c in chains]
    i = st.selectbox("Chain", range(len(chains)), format_func=lambda k: labels[k], key="oc_pick")
    row = chains[i]
    chain = fno.load_chain(row)
    if row["mode"] == "SIMULATED":
        st.markdown('<div class="iq-warn">SIMULATED chain: synthetic Black-Scholes prices and made-up OI.</div>', unsafe_allow_html=True)
    snap_t = pd.Timestamp(row["as_of"]).tz_localize(as_of.tzinfo) if pd.Timestamp(row["as_of"]).tzinfo is None else pd.Timestamp(row["as_of"])
    c = st.columns(3)
    q = clock.price_at(row["underlying"], snap_t.to_pydatetime())
    spot_src = "stored data at snapshot time" if q else "user-entered"
    spot = c[0].number_input(f"Underlying price ({spot_src})", value=float(q["price"]) if q else 0.0, key="oc_spot")
    rate = c[1].number_input("Risk-free rate (assumption, %)", 0.0, 15.0, 6.5, 0.25, key="oc_rate") / 100
    c[2].metric("Days to expiry", fmt(fno.years_to_expiry(date.fromisoformat(row["expiry"]), snap_t.to_pydatetime()) * 365, 1))
    if spot <= 0:
        st.warning("Greeks and IV are not calculated without an underlying price.")
        spot_v = None
    else:
        spot_v = spot
    en = fno.enrich(chain, spot_v, date.fromisoformat(row["expiry"]), snap_t.to_pydatetime(), rate)
    m = st.columns(4)
    m[0].metric("PCR (OI)", fmt(fno.pcr(en)))
    m[1].metric("Max pain", fmt(fno.max_pain(en), 0))
    atm = en.iloc[(en["strike"] - (spot_v or en["strike"].median())).abs().argsort()[:2]]
    straddle = atm["ltp"].sum() if len(atm) == 2 else None
    m[2].metric("ATM straddle", fmt(straddle))
    wide = en[en.get("spread_pct", pd.Series(dtype=float)) > 2]
    m[3].metric("Strikes with spread > 2%", len(wide))
    ce = en[en["option_type"] == "CE"].set_index("strike")
    pe = en[en["option_type"] == "PE"].set_index("strike")
    cols = ["ltp", "bid", "ask", "oi", "oi_change", "volume", "iv_pct", "iv_source", "delta", "gamma", "theta", "vega", "spread_pct"]
    table = ce[cols].add_prefix("CE ").join(pe[cols].add_prefix("PE "), how="outer").reset_index()
    st.dataframe(table, hide_index=True, use_container_width=True, height=420,
                 column_config={c: st.column_config.NumberColumn(c, format="%.6f" if "gamma" in c else "%.3f")
                                for c in table.columns if any(g in c for g in ("delta", "gamma", "theta", "vega"))})
    st.caption("IV source shows 'provider' when the file supplied IV, otherwise 'calculated (estimate)' from Black-Scholes "
               "(European, no dividends) — an approximation. Greeks are local estimates.")
    g = st.columns(2)
    fig = go.Figure()
    fig.add_bar(x=ce.index, y=ce["oi"], name="CE OI", marker_color="#ef5350")
    fig.add_bar(x=pe.index, y=pe["oi"], name="PE OI", marker_color="#26a69a")
    if spot_v:
        fig.add_vline(x=spot_v, line=dict(color="#f2cc60", dash="dash"))
    g[0].plotly_chart(style(fig, 320, "Open interest by strike"), use_container_width=True)
    fig2 = go.Figure()
    fig2.add_scatter(x=ce.index, y=ce["iv_pct"], name="CE IV %", mode="lines+markers")
    fig2.add_scatter(x=pe.index, y=pe["iv_pct"], name="PE IV %", mode="lines+markers")
    g[1].plotly_chart(style(fig2, 320, "IV smile"), use_container_width=True)
    dte = fno.years_to_expiry(date.fromisoformat(row["expiry"]), snap_t.to_pydatetime()) * 365
    if dte <= 2:
        st.error(f"Expiry risk: {dte:.1f} days to expiry. Gamma and liquidity can change sharply near expiry.")
    if len(wide):
        st.warning(f"Wide spreads on {len(wide)} strikes: fills may be far from LTP.")


def _futures_section(as_of) -> None:
    futs = [i for i in instruments.all_instruments() if i["segment"] == "FUT"]
    if not futs:
        st.info("No futures contracts in the instrument master.")
        return
    f = st.selectbox("Future", [x["symbol"] for x in futs], key="fut_pick")
    meta = next(x for x in futs if x["symbol"] == f)
    st.caption(f"Contract metadata: lot {meta['lot_size']}, tick {meta['tick_size']}, expiry {meta['expiry'] or 'missing'}, "
               f"source {meta['source']}.")
    und = meta.get("underlying")
    qf, qs = clock.price_at(f, as_of), clock.price_at(und, as_of) if und else None
    if not (qf and qs and meta.get("expiry")):
        st.warning("Basis needs the future's price, the underlying's price and a verified expiry date.")
    else:
        b = fno.basis(qf["price"], qs["price"], date.fromisoformat(meta["expiry"]), as_of)
        c = st.columns(4)
        c[0].metric("Future", fmt(qf["price"]))
        c[1].metric(f"Underlying ({und})", fmt(qs["price"]))
        c[2].metric("Basis", fmt(b["basis"]), f"{b['basis_pct']}%")
        c[3].metric("Annualised basis", fmt(b["annualised_pct"], 2, True))
    st.markdown("**Rollover analysis**")
    st.info("Rollover needs near- and next-month futures OI and prices for the same underlying. Import both contracts' "
            "data (with OI) to enable it; it is not estimated from a single contract.")


def render() -> None:
    st.title("F&O Analytics")
    as_of = clock.now()
    st.caption("Features turn on only when the required contract data and metadata exist. Provider-supplied values and "
               "locally calculated estimates are labelled separately.")
    tabs = st.tabs(["🧾 Option chain", "📈 Futures & basis"])
    with tabs[0]:
        _chain_section(as_of)
    with tabs[1]:
        _futures_section(as_of)
