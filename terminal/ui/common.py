"""Shared UI pieces: theme, top bar, watchlist sidebar, replay clock, formatting."""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from .. import APP_NAME, clock, db
from ..data import instruments, store
from ..data.modes import MODE_COLOURS, DataMode
from ..providers.manager import provider_manager
from ..timeutil import IST, market_status, now_ist

CSS = """
<style>
:root { --up:#26a69a; --down:#ef5350; --muted:#8b949e; --panel:#131a22; --border:#232c37; }
.block-container { padding-top: 0.8rem; padding-bottom: 1rem; max-width: 100%; }
[data-testid="stSidebar"] { min-width: 300px; }
div[data-testid="stMetric"] { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; }
div[data-testid="stMetricLabel"] p { color: var(--muted); font-size: 0.78rem; }
.iq-topbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; background:var(--panel);
  border:1px solid var(--border); border-radius:10px; padding:8px 14px; margin-bottom:10px; }
.iq-brand { font-weight:700; font-size:1.05rem; letter-spacing:0.3px; margin-right:8px; }
.iq-pill { display:inline-block; padding:2px 9px; border-radius:999px; font-size:0.74rem; font-weight:600;
  border:1px solid var(--border); color:#e6edf3; white-space:nowrap; }
.iq-sep { color: var(--border); }
.iq-muted { color: var(--muted); font-size: 0.8rem; }
.iq-up { color: var(--up); } .iq-down { color: var(--down); }
.iq-card { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:12px 14px; margin-bottom:8px; }
.iq-warn { border-left: 3px solid #d29922; padding: 6px 10px; background: rgba(210,153,34,0.08); border-radius: 4px; font-size:0.86rem; }
@media (max-width: 900px) { .iq-topbar { font-size: 0.8rem; } }
</style>
"""


PAGES: dict = {}  # url_path -> st.Page, filled by app.py


def go_to(url_path: str) -> None:
    if url_path in PAGES:
        st.switch_page(PAGES[url_path])


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def pill(text: str, colour: str = "#30363d", fg: str = "#e6edf3") -> str:
    return f'<span class="iq-pill" style="background:{colour}22;border-color:{colour};color:{fg}">{text}</span>'


def fmt(v, nd: int = 2, pct: bool = False, sign: bool = False) -> str:
    """Format a number; unavailable values show as an em dash, never as zero."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    s = f"{v:+,.{nd}f}" if sign else f"{v:,.{nd}f}"
    return s + ("%" if pct else "")


def data_modes() -> set[str]:
    return {r["mode"] for r in store.list_datasets()}


def global_mode() -> str:
    if provider_manager().live_data_ok():
        return DataMode.LIVE.value
    modes = data_modes()
    if not modes:
        return DataMode.DISCONNECTED.value
    return " + ".join(sorted(modes))


def top_bar() -> None:
    real = now_ist()
    hol, loaded = db.holiday_set()
    ms = market_status(real, store.session_settings(), hol, loaded)
    status_col = {"OPEN": "#3fb950", "PRE_OPEN": "#d29922"}.get(ms["status"], "#8b949e")
    prov = provider_manager().kotak.info
    prov_col = {"CONNECTED": "#3fb950", "DISCONNECTED": "#8b949e"}.get(prov.status.value, "#d29922")
    mode = global_mode()
    mode_col = MODE_COLOURS.get(DataMode(mode.split(" + ")[0]) if mode.split(" + ")[0] in DataMode.__members__ else None, "#8b949e")
    clk = clock.now()
    parts = [
        f'<span class="iq-brand">📈 {APP_NAME}</span>',
        pill(f"NSE: {ms['label']}", status_col),
        f'<span class="iq-muted">IST {real:%a %d %b %Y %H:%M:%S}</span>',
        pill(f"Kotak: {prov.status.value}", prov_col),
        pill(f"Data: {mode}", mode_col),
        pill(f"{clock.mode_label()}: {clk:%d %b %H:%M}", "#58a6ff"),
        pill("PAPER TRADING ONLY", "#a371f7"),
    ]
    st.markdown('<div class="iq-topbar">' + " ".join(parts) + "</div>", unsafe_allow_html=True)
    if ms.get("warning"):
        st.caption(f"⚠️ {ms['warning']} Import the NSE holiday list in Data Manager.")


def mode_banner(symbol: str | None = None) -> None:
    mode = store.symbol_mode(symbol).value if symbol and store.symbol_mode(symbol) else global_mode()
    if "SIMULATED" in mode:
        st.markdown('<div class="iq-warn">SIMULATED data: synthetic prices for demonstration only. '
                    'They do not represent any real instrument or current market conditions.</div>', unsafe_allow_html=True)
    elif "HISTORICAL" in mode:
        st.markdown('<div class="iq-warn">HISTORICAL data on a replay clock: nothing here is a live price or a live signal.</div>',
                    unsafe_allow_html=True)


# ---------- quotes ----------

def quote(symbol: str, as_of: datetime | None = None) -> dict:
    as_of = as_of or clock.now()
    q = clock.price_at(symbol, as_of)
    out = {"symbol": symbol, "last": None, "change": None, "change_pct": None, "volume": None, "time": None, "mode": None}
    if not q:
        return out
    daily = clock.bars_until(symbol, "1d", as_of + timedelta(hours=24)) if q["timeframe"] != "1d" else None
    prev_close = None
    day_vol = None
    if daily is not None and len(daily):
        prior = daily[daily["timestamp"].dt.date < as_of.date()]
        prev_close = float(prior["close"].iloc[-1]) if len(prior) else None
        intra = clock.bars_until(symbol, q["timeframe"], as_of)
        today = intra[intra["timestamp"].dt.date == as_of.date()]
        day_vol = float(today["volume"].sum()) if len(today) else None
    elif q["timeframe"] == "1d":
        d = clock.bars_until(symbol, "1d", as_of)
        prev_close = float(d["close"].iloc[-2]) if len(d) >= 2 else None
        day_vol = float(d["volume"].iloc[-1])
    out.update(last=q["price"], time=q["bar_ts"], mode=q["mode"])
    if prev_close:
        out["change"] = q["price"] - prev_close
        out["change_pct"] = (q["price"] / prev_close - 1) * 100
    if day_vol is not None and day_vol > 0:
        out["volume"] = day_vol
    return out


# ---------- watchlists ----------

def ensure_default_watchlist() -> None:
    if not db.rows("SELECT id FROM watchlists"):
        db.execute("INSERT INTO watchlists (name, created) VALUES (?, ?)", ("Default", db.now_str()))


def watchlist_items(wid: int) -> list[str]:
    return [r["symbol"] for r in db.rows("SELECT symbol FROM watchlist_items WHERE watchlist_id = ? ORDER BY position, symbol", (wid,))]


def add_to_watchlist(wid: int, symbol: str) -> None:
    db.execute("INSERT OR IGNORE INTO watchlist_items (watchlist_id, symbol, position) VALUES (?, ?, ?)",
               (wid, symbol.upper(), len(watchlist_items(wid))))


def watchlist_sidebar() -> None:
    ensure_default_watchlist()
    with st.sidebar:
        st.markdown("### Watchlist")
        wls = db.rows("SELECT * FROM watchlists ORDER BY id")
        names = [w["name"] for w in wls]
        sel = st.selectbox("Watchlist", names, key="wl_sel", label_visibility="collapsed")
        wid = next(w["id"] for w in wls if w["name"] == sel)
        known = sorted(set(store.symbols()) | {i["symbol"] for i in instruments.all_instruments()})
        c1, c2 = st.columns([3, 1])
        add = c1.selectbox("Add symbol", [""] + [s for s in known if s not in watchlist_items(wid)], key="wl_add",
                           label_visibility="collapsed", placeholder="Search to add…")
        if c2.button("Add", key="wl_add_btn", use_container_width=True) and add:
            add_to_watchlist(wid, add)
            st.rerun()
        items = watchlist_items(wid)
        if not items:
            st.caption("Empty. Search above to add symbols (from imported or simulated data).")
        else:
            as_of = clock.now()
            rows = [quote(s, as_of) for s in items]
            df = pd.DataFrame(rows)
            sort = st.selectbox("Sort by", ["symbol", "change_pct", "volume", "last"], key="wl_sort")
            df = df.sort_values(sort, ascending=sort == "symbol", na_position="last")
            show = pd.DataFrame({
                "Symbol": df["symbol"], "Last": df["last"].map(lambda v: fmt(v)),
                "Chg %": df["change_pct"].map(lambda v: fmt(v, 2, True, True)),
                "Vol": df["volume"].map(lambda v: fmt(v, 0)),
                "Bar": df["time"].map(lambda t: f"{t:%d-%b %H:%M}" if t is not None and not pd.isna(t) else "—"),
            })
            st.dataframe(show, hide_index=True, use_container_width=True, height=min(420, 38 + 35 * len(show)))
            st.caption(f"As of {clock.mode_label().lower()} {as_of:%d %b %H:%M} IST · '—' = unavailable, not zero.")
            rm = st.selectbox("Remove", [""] + items, key="wl_rm")
            if rm and st.button("Remove from watchlist", key="wl_rm_btn"):
                db.execute("DELETE FROM watchlist_items WHERE watchlist_id = ? AND symbol = ?", (wid, rm))
                st.rerun()
        with st.expander("New watchlist"):
            nm = st.text_input("Name", key="wl_new")
            if st.button("Create", key="wl_new_btn") and nm.strip():
                try:
                    db.execute("INSERT INTO watchlists (name, created) VALUES (?, ?)", (nm.strip(), db.now_str()))
                    st.rerun()
                except Exception:
                    st.error("A watchlist with that name already exists.")


# ---------- replay clock ----------

def clock_controls(key: str = "clk") -> datetime:
    """Replay clock controls (hidden when a verified live feed is active)."""
    if clock.is_live():
        st.info("Live clock (verified provider).")
        return clock.now()
    cur = clock.now()
    days = sorted({pd.Timestamp(r["end_ts"]).date() for r in store.list_datasets()} |
                  {d for r in store.list_datasets() for d in [pd.Timestamp(r["start_ts"]).date()]})
    with st.container(border=True):
        st.markdown("**Replay clock** <span class='iq-muted'>— steps stored data forward; never a live price</span>",
                    unsafe_allow_html=True)
        c = st.columns([1.3, 1, 0.8, 0.8, 0.8, 0.9, 0.9])
        d = c[0].date_input("Date", cur.date(), key=f"{key}_d", min_value=min(days) if days else None,
                            max_value=max(days) if days else None)
        t = c[1].time_input("Time (IST)", cur.time().replace(second=0, microsecond=0), step=300, key=f"{key}_t")
        if c[2].button("Set", key=f"{key}_set", use_container_width=True):
            clock.set_replay(datetime.combine(d, t, IST))
            st.rerun()
        for col, mins, lab in ((c[3], 5, "+5m"), (c[4], 15, "+15m"), (c[5], 60, "+1h")):
            if col.button(lab, key=f"{key}_{mins}", use_container_width=True):
                clock.advance(mins)
                st.rerun()
        if c[6].button("Next day", key=f"{key}_nd", use_container_width=True):
            nd = cur.date() + timedelta(days=1)
            while nd.weekday() >= 5:
                nd += timedelta(days=1)
            clock.set_replay(datetime.combine(nd, time(9, 30), IST))
            st.rerun()
    return clock.now()


def ask_ai_box(context_name: str, data: dict, rules_text: str, key: str) -> None:
    """AI explanation panel. Falls back to deterministic text when AI is off or unavailable."""
    from .. import ai

    enabled = bool(db.get_setting("ai_enabled", False))
    with st.expander("💬 Explain this" + (" (AI assistant)" if enabled and ai.available() else " (rules-based)")):
        st.markdown(rules_text)
        if enabled and ai.available():
            q = st.text_input("Ask a question about this " + context_name, key=f"{key}_q")
            if st.button("Ask", key=f"{key}_ask") and q.strip():
                with st.spinner("Asking the AI assistant…"):
                    r = ai.ask(q, {"context": context_name, **data})
                (st.markdown if r["ok"] else st.warning)(r["text"])
                st.caption(r["source"] + ". Numbers come from the terminal's deterministic engine.")
        elif enabled:
            st.caption("AI assistant enabled but no ANTHROPIC_API_KEY in the local .env file.")
