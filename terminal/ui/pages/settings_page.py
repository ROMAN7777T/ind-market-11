import pandas as pd
import streamlit as st

from ... import ai, db
from ...config import DEFAULT_PAPER, DEFAULT_RISK, DEFAULT_SESSION
from ...models import validate_section
from ...providers.base import ProviderStatus
from ...providers.kotak_neo import REQUIRED_ENV
from ...providers.manager import provider_manager
from ..common import pill


@st.dialog("Connect Kotak Neo — setup")
def _connect_dialog() -> None:
    k = provider_manager().kotak
    st.markdown(
        "This runs **local checks only**. Nothing is sent to Kotak in this version: the real login flow will be added in a "
        "future session after verifying the current official Kotak Neo documentation, SDK and your account permissions.\n\n"
        "**Never paste credentials into chat or into this app.** Put them in the local `.env` file:\n"
        f"`{', '.join(REQUIRED_ENV)}` (placeholder names, to be confirmed against the official docs).\n\n"
        "Order placement is permanently disabled: this terminal is paper-only.")
    if st.checkbox("I understand that this only checks local setup and places no orders", key="kc_ok"):
        if st.button("Run setup checks", type="primary"):
            info = k.connect(user_initiated=True)
            st.session_state["kotak_msg"] = info.message
            st.rerun()


def _connections() -> None:
    k = provider_manager().kotak
    info = k.info
    col = {"CONNECTED": "#3fb950", "DISCONNECTED": "#8b949e"}.get(info.status.value, "#d29922")
    with st.container(border=True):
        st.markdown(f"### Kotak Neo &nbsp; {pill(info.status.value, col)}", unsafe_allow_html=True)
        c = st.columns(4)
        c[0].metric("Status", info.status.value)
        c[1].metric("SDK", info.sdk or "not verified")
        c[2].metric("SDK version", info.sdk_version or "—")
        c[3].metric("Live data", "yes" if info.live_data else "no")
        st.caption(f"Last successful connection: {info.last_connected or 'never'}")
        if st.session_state.get("kotak_msg"):
            (st.info if info.status != ProviderStatus.ERROR else st.error)(st.session_state["kotak_msg"])
        b = st.columns(3)
        from ...auth import hosted
        if hosted():
            st.warning("This is a hosted copy. Broker connections are disabled here: connect Kotak only on your own computer.")
        elif info.status in (ProviderStatus.DISCONNECTED, ProviderStatus.SETUP_REQUIRED, ProviderStatus.ERROR):
            if b[0].button("🔌 Connect Kotak", type="primary", use_container_width=True):
                _connect_dialog()
        if info.status != ProviderStatus.DISCONNECTED and b[1].button("Disconnect", use_container_width=True):
            k.disconnect()
            st.session_state["kotak_msg"] = "Disconnected."
            st.rerun()
        if b[2].button("Safe connection test", use_container_width=True):
            st.json(k.test_connection())
        st.markdown("**Capabilities**")
        st.dataframe(pd.DataFrame([{"feature": f, "status": s} for f, s in info.capabilities.items()]), hide_index=True,
                     use_container_width=True)
        st.caption("See docs/KOTAK_INTEGRATION.md for how the connection will be enabled later. The app is fully usable "
                   "without it: historical analysis, backtesting and paper trading all run offline.")
    log = db.rows("SELECT ts, provider, event, detail FROM connection_log ORDER BY id DESC LIMIT 20")
    if log:
        with st.expander("Connection log (secrets redacted)"):
            st.dataframe(pd.DataFrame(log), hide_index=True, use_container_width=True)


def _section_form(name: str, defaults: dict, title: str, help_text: str) -> None:
    cur = db.get_section(name, defaults)
    with st.form(f"form_{name}"):
        st.markdown(f"**{title}**")
        st.caption(help_text)
        new = {}
        cols = st.columns(3)
        for i, (k, v) in enumerate(defaults.items()):
            col = cols[i % 3]
            label = k.replace("_", " ")
            if isinstance(v, bool):
                new[k] = col.checkbox(label, bool(cur[k]))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                new[k] = col.number_input(label, value=float(cur[k]) if isinstance(v, float) else int(cur[k]))
            elif isinstance(v, list):
                new[k] = [x.strip().upper() for x in col.text_input(label + " (comma separated)", ", ".join(cur[k])).split(",") if x.strip()]
            else:
                new[k] = col.text_input(label, str(cur[k]))
        a, b = st.columns(2)
        if a.form_submit_button("Save"):
            clean, errors = validate_section(name, new)
            if errors:
                st.error("Not saved:\n" + "\n".join(f"- {e}" for e in errors))
            else:
                db.set_setting(name, clean)
                st.success("Saved.")
        if b.form_submit_button("Restore defaults"):
            db.set_setting(name, defaults)
            st.success("Defaults restored.")


def render() -> None:
    st.title("Settings & Connections")
    tabs = st.tabs(["🔌 Connections", "🛡️ Risk engine", "🕘 Session times", "📝 Paper trading", "🤖 AI assistant", "ℹ️ Safety"])
    with tabs[0]:
        _connections()
    with tabs[1]:
        _section_form("risk", DEFAULT_RISK, "Central risk engine (research defaults)",
                      "Percentages of paper equity. Exits are never blocked. These are configurable defaults, not guarantees of safety.")
    with tabs[2]:
        _section_form("session", DEFAULT_SESSION, "NSE session times (IST, HH:MM)",
                      "Verify against the exchange's current timings. Flat-by should be earlier than your broker's auto square-off.")
    with tabs[3]:
        _section_form("paper", DEFAULT_PAPER, "Paper trading", "Automation stays off unless you switch it on.")
    with tabs[4]:
        en = st.toggle("Enable the optional AI assistant panel", bool(db.get_setting("ai_enabled", False)))
        if en != bool(db.get_setting("ai_enabled", False)):
            db.set_setting("ai_enabled", en)
        st.write(f"API key in local .env: {'found' if ai.available() else 'not set'} (the key itself is never shown or stored in the database).")
        st.caption(f"Model: {ai.MODEL}. The assistant receives only the data shown next to each 'Explain this' panel, after "
                   "secret redaction, and explains it. Prices, signals, risk and P&L are always computed by the terminal itself. "
                   "Server-side model fallback on refusals is enabled. Without a key, rules-based explanations are used.")
    with tabs[5]:
        st.markdown("""
- **Paper only.** No code path exists from this application to a broker order endpoint.
- **Kotak disconnected by default.** No automatic login, no background connection, no credential prompts.
- **Local only.** The server listens on `localhost`; data, logs and the database stay in this folder.
- **Secrets** live only in the local `.env` file (see `.env.example`), are redacted from logs, and are never stored in SQLite.
- **Data modes** are always shown: SIMULATED and HISTORICAL data never appear as live prices.
- **Not financial advice.** Signals are rule matches; backtests describe the past.
""")
