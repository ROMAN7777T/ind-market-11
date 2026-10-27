import pandas as pd
import plotly.express as px
import streamlit as st

from ... import db, paper
from ..charts import style
from ..common import fmt


def render() -> None:
    st.title("Trade Journal & Analytics")
    st.caption("Closed PAPER trades only, after simulated costs.")
    t = paper.trades()
    if not t:
        st.info("No closed paper trades yet. Place and close trades in **Paper Trading** (use the replay clock to step forward).")
        return
    df = pd.DataFrame(t)
    df["exit_day"] = df["exit_ts"].str[:10]
    wins = df[df["net_pnl"] > 0]
    loss = df[df["net_pnl"] <= 0]
    k = st.columns(6)
    k[0].metric("Trades", len(df))
    k[1].metric("Net P&L", f"₹{fmt(df['net_pnl'].sum(), sign=True)}")
    k[2].metric("Win rate", fmt(len(wins) / len(df) * 100, 1, True))
    k[3].metric("Profit factor", fmt(wins["net_pnl"].sum() / -loss["net_pnl"].sum() if len(loss) and loss["net_pnl"].sum() < 0 else None))
    k[4].metric("Avg R", fmt(df["r_multiple"].mean(), 3))
    k[5].metric("Costs paid", f"₹{fmt(df['costs'].sum())}")
    c = st.columns(2)
    eq = df.sort_values("exit_ts").assign(cum=lambda d: d["net_pnl"].cumsum())
    c[0].plotly_chart(style(px.line(eq, x="exit_ts", y="cum", markers=True), 300, "Cumulative net P&L"), use_container_width=True)
    by_day = df.groupby("exit_day", as_index=False)["net_pnl"].sum()
    c[1].plotly_chart(style(px.bar(by_day, x="exit_day", y="net_pnl", color=by_day["net_pnl"] > 0,
                                   color_discrete_map={True: "#26a69a", False: "#ef5350"}), 300, "P&L by day"), use_container_width=True)
    c2 = st.columns(2)
    by_s = df.groupby("strategy", as_index=False).agg(trades=("id", "count"), net=("net_pnl", "sum"), avg_r=("r_multiple", "mean"))
    c2[0].dataframe(by_s, hide_index=True, use_container_width=True)
    c2[1].plotly_chart(style(px.histogram(df, x="r_multiple", nbins=20), 260, "R-multiple distribution"), use_container_width=True)
    st.markdown("**Journal** — add notes and tags, then save.")
    ed = st.data_editor(df[["id", "symbol", "direction", "qty", "entry_ts", "entry_price", "exit_ts", "exit_price", "net_pnl",
                            "r_multiple", "strategy", "exit_reason", "notes", "tags"]],
                        disabled=["id", "symbol", "direction", "qty", "entry_ts", "entry_price", "exit_ts", "exit_price",
                                  "net_pnl", "r_multiple", "strategy", "exit_reason"],
                        hide_index=True, use_container_width=True, key="jr_ed")
    if st.button("Save notes"):
        for _, r in ed.iterrows():
            db.execute("UPDATE paper_trades SET notes = ?, tags = ? WHERE id = ?", (r["notes"], r["tags"], int(r["id"])))
        st.success("Saved.")
    st.download_button("Export journal CSV", paper.export_csv(t), "paper_trade_journal.csv")
