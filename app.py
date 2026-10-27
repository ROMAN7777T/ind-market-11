"""IndQuant Terminal - local Indian-market research, backtesting and PAPER trading.

Run:  streamlit run app.py   (opens http://localhost:8501)
Kotak stays DISCONNECTED until you connect it yourself from Settings. No real orders exist.
"""
import streamlit as st

st.set_page_config(page_title="IndQuant Terminal", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

from terminal import db  # noqa: E402
from terminal.secure import load_env, setup_logging  # noqa: E402
from terminal.ui import common  # noqa: E402
from terminal.ui.pages import (backtest_lab, chart_terminal, data_manager, fno_analytics, journal, market_watch,  # noqa: E402
                               news_intel, overview, paper_trading, scanner_page, settings_page)


@st.cache_resource
def _bootstrap() -> bool:
    load_env()  # reads the local .env only; never connects to a broker
    setup_logging()
    db.init_db()
    return True


_bootstrap()
common.inject_css()


def _gate() -> None:
    """Hosted copies need a password; local use does not. Fails closed when no password is set."""
    import time

    from terminal import auth

    remote = auth.hosted()
    expected = auth.configured_password()
    if not remote and expected is None:
        return
    if st.session_state.get("auth_ok"):
        return
    st.title("📈 IndQuant Terminal")
    if expected is None:
        st.error("This copy is being reached over the network, but no password is configured, so it will not open. "
                 "Set `app_password` in the host's Secrets (see docs/DEPLOYMENT.md).")
        st.stop()
    fails = st.session_state.get("auth_fails", 0)
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        ok = st.form_submit_button("Open terminal")
    if ok:
        if fails >= 5:
            time.sleep(min(30, 2 ** (fails - 4)))  # slow down repeated guesses
        if auth.check_password(pw, expected):
            st.session_state["auth_ok"] = True
            st.session_state["auth_fails"] = 0
            st.rerun()
        st.session_state["auth_fails"] = fails + 1
        st.error("Wrong password.")
    st.caption("Research and paper trading only. No real orders can be placed from this application.")
    st.stop()


_gate()

PAGES = [
    st.Page(overview.render, title="Overview", icon="🏠", url_path="overview", default=True),
    st.Page(chart_terminal.render, title="Advanced Chart Terminal", icon="📊", url_path="charts"),
    st.Page(market_watch.render, title="Market Watch", icon="👁️", url_path="marketwatch"),
    st.Page(scanner_page.render, title="Strategy Scanner", icon="🎯", url_path="scanner"),
    st.Page(news_intel.render, title="News Intelligence", icon="📰", url_path="news"),
    st.Page(fno_analytics.render, title="F&O Analytics", icon="🧮", url_path="fno"),
    st.Page(backtest_lab.render, title="Backtesting Lab", icon="🧪", url_path="backtest"),
    st.Page(paper_trading.render, title="Paper Trading", icon="📝", url_path="paper"),
    st.Page(journal.render, title="Trade Journal & Analytics", icon="📒", url_path="journal"),
    st.Page(data_manager.render, title="Data Manager", icon="🗄️", url_path="data"),
    st.Page(settings_page.render, title="Settings & Connections", icon="⚙️", url_path="settings"),
]
common.PAGES.update({p.url_path: p for p in PAGES})
nav = st.navigation(PAGES)
common.top_bar()
common.watchlist_sidebar()
nav.run()
