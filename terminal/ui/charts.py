"""Plotly chart builders for the terminal."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .. import indicators as ind
from ..data.validation import INTRADAY

UP, DOWN = "#26a69a", "#ef5350"
GRID = "#1f2630"
OVERLAYS = ["EMA 9", "EMA 20", "EMA 50", "SMA 20", "SMA 50", "SMA 200", "VWAP", "Bollinger", "Support/Resistance"]
PANES = ["Volume", "RSI", "MACD", "ATR"]
OVERLAY_STYLE = {"EMA 9": ("ema9", "#f2cc60"), "EMA 20": ("ema20", "#58a6ff"), "EMA 50": ("ema50", "#a371f7"),
                 "SMA 20": ("sma20", "#79c0ff"), "SMA 50": ("sma50", "#d2a8ff"), "SMA 200": ("sma200", "#ffa657"),
                 "VWAP": ("vwap", "#f778ba")}

PLOT_CONFIG = {
    "displaylogo": False,
    "scrollZoom": True,
    "modeBarButtonsToAdd": ["drawline", "drawopenpath", "drawrect", "drawcircle", "eraseshape"],
    "toImageButtonOptions": {"format": "png", "scale": 2},
}


def candle_figure(df_full: pd.DataFrame, tf: str, session: dict, title: str, overlays: list[str], panes: list[str],
                  bars: int = 300, mode: str = "", height: int = 560, levels: dict | None = None,
                  x_range: tuple | None = None) -> go.Figure:
    intraday = tf in INTRADAY
    # Indicators are computed on the full history, then the view is trimmed, so warm-up is handled honestly.
    work = df_full.tail(bars + 400)
    if intraday and len(work) < len(df_full):
        first_day = work["timestamp"].dt.date.iloc[0]
        work = work[work["timestamp"].dt.date != first_day]  # start on a whole session so VWAP is anchored correctly
    data = ind.add_all(work.reset_index(drop=True), intraday)
    view = data.tail(bars).reset_index(drop=True)
    if "Volume" in panes and view["volume"].sum() <= 0:
        panes = [p for p in panes if p != "Volume"]  # spot indices have no traded volume: no empty pane
        title = f"{title} (no traded volume)"
    rows = 1 + len(panes)
    heights = [0.62] + [0.38 / max(1, len(panes))] * len(panes) if panes else [1.0]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.025, row_heights=heights)
    # Category axis of bar labels: non-trading time is skipped natively. (Hour-pattern rangebreaks are far
    # too slow in Plotly.js once several charts are on screen.)
    x = view["timestamp"].dt.strftime("%d %b %H:%M" if intraday else "%d %b %Y")
    fig.add_trace(go.Candlestick(x=x, open=view["open"], high=view["high"], low=view["low"], close=view["close"],
                                 name="Price", increasing_line_color=UP, decreasing_line_color=DOWN,
                                 increasing_fillcolor=UP, decreasing_fillcolor=DOWN), row=1, col=1)
    for o in overlays:
        if o in OVERLAY_STYLE:
            col, colour = OVERLAY_STYLE[o]
            if col in view and view[col].notna().any():
                fig.add_trace(go.Scatter(x=x, y=view[col], name=o, line=dict(color=colour, width=1.2)), row=1, col=1)
        elif o == "Bollinger":
            fig.add_trace(go.Scatter(x=x, y=view["bb_upper"], name="BB upper", line=dict(color="#6e7681", width=1, dash="dot")), row=1, col=1)
            fig.add_trace(go.Scatter(x=x, y=view["bb_lower"], name="BB lower", line=dict(color="#6e7681", width=1, dash="dot"),
                                     fill="tonexty", fillcolor="rgba(110,118,129,0.07)"), row=1, col=1)
        elif o == "Support/Resistance":
            sr = ind.support_resistance(data.tail(min(len(data), bars * 2)))
            for lvl in sr["support"]:
                fig.add_hline(y=lvl, line=dict(color=UP, width=1, dash="dash"), opacity=0.6, row=1, col=1,
                              annotation_text=f"S {lvl:,.2f}", annotation_font_size=10)
            for lvl in sr["resistance"]:
                fig.add_hline(y=lvl, line=dict(color=DOWN, width=1, dash="dash"), opacity=0.6, row=1, col=1,
                              annotation_text=f"R {lvl:,.2f}", annotation_font_size=10)
    for name, lvl in (levels or {}).items():
        if lvl is not None and not pd.isna(lvl):
            fig.add_hline(y=lvl, line=dict(color="#f2cc60", width=1), row=1, col=1, annotation_text=f"{name} {lvl:,.2f}",
                          annotation_font_size=10)
    r = 2
    for p in panes:
        if p == "Volume":
            colours = np.where(view["close"] >= view["open"], UP, DOWN)
            fig.add_trace(go.Bar(x=x, y=view["volume"], name="Volume", marker_color=colours, opacity=0.7), row=r, col=1)
        elif p == "RSI":
            fig.add_trace(go.Scatter(x=x, y=view["rsi14"], name="RSI 14", line=dict(color="#d2a8ff", width=1.2)), row=r, col=1)
            for lv in (30, 70):
                fig.add_hline(y=lv, line=dict(color="#6e7681", width=1, dash="dot"), row=r, col=1)
            fig.update_yaxes(range=[0, 100], row=r, col=1)
        elif p == "MACD":
            fig.add_trace(go.Bar(x=x, y=view["hist"], name="MACD hist",
                                 marker_color=np.where(view["hist"].fillna(0) >= 0, UP, DOWN), opacity=0.6), row=r, col=1)
            fig.add_trace(go.Scatter(x=x, y=view["macd"], name="MACD", line=dict(color="#58a6ff", width=1.1)), row=r, col=1)
            fig.add_trace(go.Scatter(x=x, y=view["signal"], name="Signal", line=dict(color="#ffa657", width=1.1)), row=r, col=1)
        elif p == "ATR":
            fig.add_trace(go.Scatter(x=x, y=view["atr14"], name="ATR 14", line=dict(color="#ffa657", width=1.2)), row=r, col=1)
        fig.add_annotation(text=p, xref="x domain", yref="y domain", x=0.0, y=1.0, xanchor="left", yanchor="top",
                           showarrow=False, font=dict(size=9, color="#8b949e"), row=r, col=1)
        r += 1
    pos = np.unique(np.linspace(0, max(0, len(x) - 1), min(6, len(x))).astype(int))
    fig.update_xaxes(type="category", tickmode="array", tickvals=x.iloc[pos].tolist(), ticktext=x.iloc[pos].tolist(),
                     tickangle=0, tickfont=dict(size=9), showgrid=True, gridcolor=GRID,
                     showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1, spikecolor="#6e7681",
                     rangeslider_visible=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, showspikes=True, spikemode="across", spikethickness=1,
                     spikecolor="#6e7681", side="right", automargin=False)
    fig.update_xaxes(automargin=False)
    if x_range:
        lo, hi = (pd.Timestamp(v) for v in x_range)
        ts = view["timestamp"].dt.tz_localize(None)
        idx = np.where((ts >= lo) & (ts <= hi))[0]
        if len(idx):
            fig.update_xaxes(range=[idx[0] - 0.5, idx[-1] + 0.5])
    fig.update_layout(
        title=dict(text=f"{title} · {tf} · <span style='color:#d29922'>{mode}</span>", font=dict(size=13), x=0.01),
        template="plotly_dark", paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14", height=height,
        # Fixed margins and an in-plot legend: Plotly's automargin can relayout forever in narrow grid panels.
        margin=dict(l=10, r=62, t=34, b=30), hovermode="x unified", dragmode="pan", showlegend=True,
        legend=dict(orientation="h", y=0.995, yanchor="top", x=0.01, font=dict(size=9), bgcolor="rgba(11,15,20,0.6)"),
        newshape=dict(line_color="#f2cc60", line_width=1.5), uirevision=title + tf,
    )
    return fig


def equity_figure(eq: pd.DataFrame, title: str = "Equity") -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.04)
    fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq["equity"], name="Equity", line=dict(color="#58a6ff", width=1.4)), row=1, col=1)
    fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq["drawdown_pct"], name="Drawdown %", fill="tozeroy",
                             line=dict(color=DOWN, width=1)), row=2, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14", height=420,
                      margin=dict(l=8, r=8, t=30, b=8), title=dict(text=title, font=dict(size=13)), hovermode="x unified")
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig


def style(fig: go.Figure, height: int = 320, title: str | None = None) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14", height=height,
                      margin=dict(l=8, r=8, t=34 if title else 10, b=8), title=dict(text=title or "", font=dict(size=13)))
    fig.update_xaxes(gridcolor=GRID)
    fig.update_yaxes(gridcolor=GRID)
    return fig
