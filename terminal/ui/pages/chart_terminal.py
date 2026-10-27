import pandas as pd
import streamlit as st

from ... import clock
from ... import indicators as ind
from ...data import store
from ...data.validation import INTRADAY
from .. import lower_panel
from ..charts import OVERLAYS, PANES, PLOT_CONFIG, candle_figure
from ..common import clock_controls, fmt, mode_banner, quote

LAYOUTS = {"1 chart": 1, "2 side by side": 2, "3 charts": 3, "2 x 2 grid": 4}


def _panel(i: int, symbols: list[str], as_of, height: int, x_range) -> None:
    default = st.session_state.get("chart_symbol") if i == 0 else None
    idx = symbols.index(default) if default in symbols else min(i, len(symbols) - 1)
    c = st.columns([1.4, 0.8, 0.8])
    sym = c[0].selectbox("Instrument", symbols, index=idx, key=f"p{i}_sym")
    tfs = store.timeframes_for(sym)
    tf = c[1].selectbox("Timeframe", tfs, index=tfs.index("5m") if "5m" in tfs else 0, key=f"p{i}_tf")
    bars = c[2].number_input("Bars", 50, 2000, 240 if tf in INTRADAY else 180, 10, key=f"p{i}_bars")
    with st.expander("Indicators & tools", expanded=False):
        ov = st.multiselect("Overlays", OVERLAYS, default=["EMA 20", "VWAP"] if tf in INTRADAY else ["SMA 20", "SMA 50"], key=f"p{i}_ov")
        pn = st.multiselect("Lower panes", PANES, default=["Volume", "RSI"], key=f"p{i}_pn")
        st.caption("Toolbar: zoom, pan, draw line / path / rectangle / circle, erase shape, reset axes (double-click), "
                   "download PNG. Crosshair follows the cursor; hover shows OHLC and indicator values.")
    df = clock.bars_until(sym, tf, as_of)
    if df.empty:
        st.warning(f"No closed {tf} bars for {sym} at the clock time.")
        return
    q = quote(sym, as_of)
    trend = ind.trend_state(df["close"])
    vol = ind.volatility_state(df)
    mode = store.symbol_mode(sym).value
    st.markdown(f"**{sym}** {fmt(q['last'])} "
                f"<span class='{'iq-up' if (q['change'] or 0) >= 0 else 'iq-down'}'>{fmt(q['change'], 2, sign=True)} "
                f"({fmt(q['change_pct'], 2, True, True)})</span> · Trend **{trend}** · Volatility **{vol}** · "
                f"<span class='iq-muted'>last closed bar {df['timestamp'].iloc[-1]:%d %b %H:%M} IST</span>",
                unsafe_allow_html=True)
    if len(df) < 200:
        st.caption(f"Only {len(df)} bars: long indicators (SMA 200, etc.) stay blank during warm-up.")
    fig = candle_figure(df, tf, store.session_settings(), sym, ov, pn, int(bars), mode, height, x_range=x_range)
    st.plotly_chart(fig, use_container_width=True, config=PLOT_CONFIG, key=f"p{i}_chart")


def render() -> None:
    st.title("Advanced Chart Terminal")
    symbols = store.symbols()
    if not symbols:
        st.info("No data yet. Generate SIMULATED demo data on **Overview** or import CSVs in **Data Manager**.")
        return
    mode_banner()
    as_of = clock_controls("chart")
    top = st.columns([1.2, 1, 2])
    layout = top[0].radio("Layout", list(LAYOUTS), horizontal=True, key="chart_layout")
    sync = top[1].toggle("Sync time range", value=False, key="chart_sync",
                         help="Applies one date window to every panel (within each panel's loaded bars; raise 'Bars' to see further "
                              "back). Crosshair syncing across separate charts is not supported by Streamlit; each panel "
                              "has its own crosshair.")
    x_range = None
    if sync:
        days = sorted({d for s in symbols for d in clock.bars_until(s, "1d", as_of)["timestamp"].dt.date.tail(400)})
        if days:
            lo, hi = top[2].select_slider("Window", options=days, value=(days[max(0, len(days) - 5)], days[-1]), key="chart_win")
            x_range = (pd.Timestamp(lo).strftime("%Y-%m-%d 09:00"), pd.Timestamp(hi).strftime("%Y-%m-%d 15:40"))
    n = LAYOUTS[layout]
    height = 640 if n == 1 else (520 if n == 2 else 430)
    if n == 1:
        _panel(0, symbols, as_of, height, x_range)
    elif n == 2:
        cols = st.columns(2)
        for i in range(2):
            with cols[i]:
                _panel(i, symbols, as_of, height, x_range)
    elif n == 3:
        cols = st.columns([1.3, 1])
        with cols[0]:
            _panel(0, symbols, as_of, 2 * height - 100, x_range)
        with cols[1]:
            _panel(1, symbols, as_of, height - 70, x_range)
            _panel(2, symbols, as_of, height - 70, x_range)
    else:
        for r in range(2):
            cols = st.columns(2)
            for c in range(2):
                with cols[c]:
                    _panel(r * 2 + c, symbols, as_of, height, x_range)
    st.divider()
    lower_panel.render()
