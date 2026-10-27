import numpy as np
import pandas as pd
import streamlit as st

from ... import clock
from ... import indicators as ind
from ...data import instruments, store
from ..common import fmt, go_to, mode_banner, quote


@st.cache_data(ttl=120, show_spinner=False)
def _monitor(as_of_iso: str, _symbols: tuple) -> pd.DataFrame:
    from datetime import datetime

    as_of = datetime.fromisoformat(as_of_iso)
    rows = []
    for s in _symbols:
        inst = instruments.get(s) or {}
        q = quote(s, as_of)
        tf = store.finest_timeframe(s)
        intra = clock.bars_until(s, tf, as_of).tail(75 * 25) if tf else pd.DataFrame()
        daily = clock.bars_until(s, "1d", as_of)
        r = {"symbol": s, "segment": inst.get("segment", "?"), "mode": q["mode"], "last": q["last"],
             "chg_pct": q["change_pct"], "volume": q["volume"], "bar": q["time"]}
        if len(intra) > 60:
            today = intra[intra["timestamp"].dt.date == as_of.date()]
            prior = daily[daily["timestamp"].dt.date < as_of.date()]
            r["gap_pct"] = (today["open"].iloc[0] / prior["close"].iloc[-1] - 1) * 100 if len(today) and len(prior) else np.nan
            r["rvol"] = ind.relative_volume(intra, 20, True).iloc[-1] if intra["volume"].sum() > 0 else np.nan
            r["intraday_trend"] = ind.trend_state(intra["close"])
            r["rsi14"] = ind.rsi(intra["close"]).iloc[-1]
            if intra["volume"].sum() > 0:
                vw = ind.vwap(intra).iloc[-1]
                r["vs_vwap"] = "above" if q["last"] and q["last"] > vw else "below"
        if len(daily) > 30:
            r["daily_trend"] = ind.trend_state(daily["close"])
            r["volatility"] = ind.volatility_state(daily, 14, min(100, len(daily) - 5))
            r["atr_pct"] = ind.atr(daily).iloc[-1] / daily["close"].iloc[-1] * 100
        rows.append(r)
    return pd.DataFrame(rows)


def render() -> None:
    st.title("Market Watch")
    symbols = store.symbols()
    if not symbols:
        st.info("No data yet. Generate SIMULATED demo data on **Overview** or import CSVs in **Data Manager**.")
        return
    mode_banner()
    as_of = clock.now()
    st.caption(f"Values as of the {clock.mode_label().lower()} {as_of:%d %b %Y %H:%M} IST, computed only from closed bars.")
    df = _monitor(as_of.isoformat(), tuple(symbols))
    f = st.columns([1.4, 1, 1, 1, 1])
    q = f[0].text_input("Search", key="mw_q", placeholder="Symbol contains…")
    segs = f[1].multiselect("Segment", sorted(df["segment"].unique()), key="mw_seg")
    trend = f[2].multiselect("Intraday trend", ["UPTREND", "DOWNTREND", "SIDEWAYS"], key="mw_tr")
    gap = f[3].number_input("|Gap| ≥ %", 0.0, 20.0, 0.0, 0.25, key="mw_gap")
    rv = f[4].number_input("Rel. volume ≥", 0.0, 20.0, 0.0, 0.25, key="mw_rv")
    v = df.copy()
    if q:
        v = v[v["symbol"].str.contains(q.upper())]
    if segs:
        v = v[v["segment"].isin(segs)]
    if trend and "intraday_trend" in v:
        v = v[v["intraday_trend"].isin(trend)]
    if gap and "gap_pct" in v:
        v = v[v["gap_pct"].abs() >= gap]
    if rv and "rvol" in v:
        v = v[v["rvol"] >= rv]

    eq = df[df["segment"] == "EQ"]
    b = st.columns(5)
    adv, dec = int((eq["chg_pct"] > 0).sum()), int((eq["chg_pct"] < 0).sum())
    b[0].metric("Advancers (EQ in dataset)", adv)
    b[1].metric("Decliners", dec)
    b[2].metric("A/D ratio", fmt(adv / dec if dec else None))
    b[3].metric("Gap ups ≥ 1%", int((df.get("gap_pct", pd.Series(dtype=float)) >= 1).sum()))
    b[4].metric("Gap downs ≤ -1%", int((df.get("gap_pct", pd.Series(dtype=float)) <= -1).sum()))
    st.caption("Breadth is measured only over the equities stored in this terminal, not the whole NSE market.")

    st.dataframe(
        v, hide_index=True, use_container_width=True, height=480,
        column_config={
            "last": st.column_config.NumberColumn("Last", format="%.2f"),
            "chg_pct": st.column_config.NumberColumn("Chg %", format="%+.2f"),
            "volume": st.column_config.NumberColumn("Volume", format="%d"),
            "gap_pct": st.column_config.NumberColumn("Gap %", format="%+.2f"),
            "rvol": st.column_config.NumberColumn("Rel vol", format="%.2f"),
            "rsi14": st.column_config.NumberColumn("RSI 14", format="%.1f"),
            "atr_pct": st.column_config.NumberColumn("ATR % (daily)", format="%.2f"),
            "bar": st.column_config.DatetimeColumn("Last bar", format="DD MMM HH:mm"),
        })
    st.caption("Blank cells = unavailable (no volume for spot indices, insufficient history), never zero.")
    c = st.columns([2, 1])
    pick = c[0].selectbox("Open in chart", v["symbol"].tolist() or symbols, key="mw_open")
    if c[1].button("Open chart →", use_container_width=True):
        st.session_state["chart_symbol"] = pick
        st.session_state["p0_sym"] = pick
        go_to("charts")
