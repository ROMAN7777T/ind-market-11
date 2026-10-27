import io
import zipfile

import pandas as pd
import streamlit as st

from ... import db
from ...data import instruments, simulated, store
from ...data.validation import TF_MINUTES
from ..common import add_to_watchlist


def render() -> None:
    st.title("Data Manager")
    tabs = st.tabs(["📦 Datasets", "⬆️ Import candles", "🧾 Instrument master", "📅 Holiday calendar", "🧪 Simulated data", "💾 Export"])
    with tabs[0]:
        ds = store.list_datasets()
        if not ds:
            st.info("No datasets yet.")
        else:
            st.dataframe(pd.DataFrame([{"symbol": d["symbol"], "timeframe": d["timeframe"], "mode": d["mode"], "source": d["source"],
                                        "rows": d["rows"], "from": d["start_ts"], "to": d["end_ts"], "imported": d["imported_at"],
                                        "issues": "; ".join(d["quality"].get("issues", [])) or "none"} for d in ds]),
                         hide_index=True, use_container_width=True, height=380)
            c = st.columns([2, 1, 1])
            pick = c[0].selectbox("Delete dataset", [f"{d['symbol']}|{d['timeframe']}" for d in ds], key="dm_del")
            word = c[1].text_input("Type DELETE", key="dm_del_w")
            if c[2].button("Delete", disabled=word != "DELETE"):
                s, tf = pick.split("|")
                store.delete_dataset(s, tf)
                st.success(f"Deleted {s} {tf}.")
                st.rerun()
    with tabs[1]:
        st.markdown("CSV columns: `timestamp, open, high, low, close, volume` (aliases date/datetime accepted). Timestamps "
                    "without a zone are read as IST; intraday timestamps are bar **start** times. Every row is validated: "
                    "invalid OHLC, duplicates and out-of-session bars are dropped and reported. Re-importing merges.")
        up = st.file_uploader("Candles CSV", type=["csv"], key="dm_up")
        c = st.columns(4)
        sym = c[0].text_input("Symbol (as on NSE, e.g. RELIANCE)", key="dm_sym").upper().strip()
        tf = c[1].selectbox("Timeframe", list(TF_MINUTES), index=2, key="dm_tf")
        seg = c[2].selectbox("Segment", ["EQ", "IDX", "FUT", "OPT"], key="dm_seg")
        src = c[3].text_input("Source note", "CSV import", key="dm_src")
        c2 = st.columns(4)
        tick = c2[0].number_input("Tick size (from exchange)", 0.0, 100.0, 0.0, 0.01, key="dm_tick", help="0 = unknown")
        lot = c2[1].number_input("Lot size (F&O)", 0, 100000, 0, key="dm_lot")
        expiry = c2[2].text_input("Expiry (F&O, YYYY-MM-DD)", key="dm_exp")
        wl = c2[3].checkbox("Add to first watchlist", True, key="dm_wl")
        if up and sym and st.button("Validate and import", type="primary"):
            try:
                q = store.import_csv(up, sym, tf, src)
                if not instruments.get(sym):
                    instruments.upsert([{"symbol": sym, "name": sym, "segment": seg, "exchange": "NSE", "tick_size": tick or None,
                                         "lot_size": lot or (1 if seg in ("EQ", "IDX") else None), "expiry": expiry or None}], "User import")
                if wl:
                    add_to_watchlist(db.rows("SELECT id FROM watchlists ORDER BY id LIMIT 1")[0]["id"], sym)
                st.success(f"Imported {q['rows_out']} of {q['rows_in']} rows as HISTORICAL data.")
                for i in q["issues"]:
                    st.warning(i)
            except Exception as e:
                st.error(f"Import failed, existing data kept: {e}")
        st.caption("A sample format is in sample_data/candles_template.csv.")
    with tabs[2]:
        st.markdown("Import a contract master (CSV): `symbol, name, segment (EQ/IDX/FUT/OPT), exchange, underlying, expiry, "
                    "strike, option_type, tick_size, lot_size`. Use the exchange's or your broker's current file: lot sizes, "
                    "tick sizes and expiries change and are never hardcoded here.")
        up = st.file_uploader("Instrument master CSV", type=["csv"], key="dm_inst")
        if up and st.button("Import instruments"):
            try:
                st.success(f"{instruments.import_csv(up)} instruments upserted.")
            except Exception as e:
                st.error(str(e))
        inst = instruments.all_instruments()
        if inst:
            st.dataframe(pd.DataFrame(inst), hide_index=True, use_container_width=True, height=320)
    with tabs[3]:
        hol = db.rows("SELECT * FROM holidays ORDER BY date")
        st.markdown("NSE trading holidays are published in an annual exchange circular. Import them as CSV (`date, description`). "
                    "Without this list the session clock cannot detect holidays and says so.")
        up = st.file_uploader("Holidays CSV", type=["csv"], key="dm_hol")
        src = st.text_input("Source (e.g. NSE circular number)", key="dm_hol_src")
        if up and src and st.button("Import holidays"):
            try:
                h = pd.read_csv(up)
                h.columns = [c.lower().strip() for c in h.columns]
                with db.session() as conn:
                    for r in h.to_dict("records"):
                        conn.execute("INSERT OR REPLACE INTO holidays (date, description, source) VALUES (?, ?, ?)",
                                     (pd.to_datetime(r["date"]).date().isoformat(), r.get("description"), src))
                st.success(f"{len(h)} holidays imported.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
        if hol:
            st.dataframe(pd.DataFrame(hol), hide_index=True, use_container_width=True)
    with tabs[4]:
        st.markdown("Synthetic demonstration data. Symbols start with `SIM_` and every screen labels them **SIMULATED**.")
        n = st.slider("Sessions", 60, 400, 260, 20, key="dm_sim_n")
        seed = st.number_input("Seed", 0, 10**6, 7, key="dm_sim_seed")
        if st.button("Generate / regenerate simulated data"):
            with st.spinner("Generating…"):
                for s in [x for x in store.symbols() if x.startswith("SIM_")]:
                    for d in [r for r in store.list_datasets() if r["symbol"] == s]:
                        store.delete_dataset(s, d["timeframe"])
                made = simulated.generate_all(int(n), int(seed))
            st.success(f"{len(made)} simulated instruments ready.")
    with tabs[5]:
        st.markdown("Export your locally generated results (paper orders, trades, journal, backtests, risk log, watchlists).")
        if st.button("Build export ZIP"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for t in ("paper_orders", "paper_trades", "paper_positions", "backtests", "risk_log", "watchlists",
                          "watchlist_items", "alerts", "strategy_settings", "news"):
                    z.writestr(f"{t}.csv", pd.DataFrame(db.rows(f"SELECT * FROM {t}")).to_csv(index=False))
            st.download_button("Download export.zip", buf.getvalue(), "indquant_export.zip")
        st.caption("Database: data/terminal.db · market data: data/market/ · logs: logs/. All files stay on this computer.")
