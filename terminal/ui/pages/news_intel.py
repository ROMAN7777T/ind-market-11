import plotly.express as px
import streamlit as st

from ... import paper
from ...news import core as news
from ...skills import analyst, insider_tracker
from ..charts import style
from ..common import ask_ai_box


def _news_tab() -> None:
    feeds = news.load_feeds()
    with st.expander("Sources (all disabled by default — nothing is fetched until you enable one and press Fetch)"):
        changed = False
        for i, f in enumerate(feeds):
            c = st.columns([3, 1, 1, 1])
            c[0].markdown(f"**{f['name']}** {'🏛️ official' if f.get('official') else ''}<br><span class='iq-muted'>{f['url']}</span>",
                          unsafe_allow_html=True)
            en = c[1].toggle("Enabled", f.get("enabled", False), key=f"feed_en_{i}")
            if en != f.get("enabled", False):
                f["enabled"], changed = en, True
            c[2].caption(f"verified: {f.get('verified', 'unverified')}")
            if c[3].button("Fetch", key=f"feed_f_{i}", disabled=not en):
                r = news.fetch_feed(f, force=False)
                (st.success if r["ok"] else st.warning)(f"{r['feed']}: {r['message']}")
        if changed:
            news.save_feeds(feeds)
        st.caption("Check each source's terms before enabling. Fetches are rate-limited (one per feed per 5 minutes), "
                   "use https only, a 15 s timeout and a 2 MB cap. Article text is treated as untrusted data.")
    with st.expander("Import announcements file (CSV or JSON)"):
        st.caption("Columns: headline, url, published_at, publisher, summary. Use this for NSE/BSE announcement exports.")
        up = st.file_uploader("File", type=["csv", "json"], key="news_up")
        src = st.text_input("Source name", "NSE announcements export", key="news_src")
        off = st.checkbox("Official exchange/regulator source", True, key="news_off")
        if up and st.button("Import", key="news_imp"):
            try:
                new, dup = news.import_file(up, src, off)
                st.success(f"{new} new items, {dup} duplicates skipped.")
            except Exception as e:
                st.error(f"Import failed: {e}")
    df = news.items(limit=500)
    if df.empty:
        st.info("No news stored yet. The section works without Kotak and without an AI key: enable a feed or import a file.")
        return
    c = st.columns(4)
    cat = c[0].multiselect("Category", sorted(df["category"].dropna().unique()), key="nw_cat")
    rel = c[1].multiselect("Relevance", ["HIGH", "MEDIUM", "LOW"], key="nw_rel")
    off_only = c[2].toggle("Official sources only", False, key="nw_off")
    sym = c[3].text_input("Instrument", key="nw_sym").upper()
    v = df
    if cat:
        v = v[v["category"].isin(cat)]
    if rel:
        v = v[v["relevance"].isin(rel)]
    if off_only:
        v = v[v["verification"].str.startswith("Official")]
    if sym:
        v = v[v["symbols"].apply(lambda s: sym in s)]
    v = v.assign(instruments=v["symbols"].apply(lambda s: ", ".join(s)))
    st.dataframe(v[["published_at", "retrieved_at", "headline", "publisher", "instruments", "category", "sentiment",
                    "relevance", "verification", "url"]], hide_index=True, use_container_width=True, height=460,
                 column_config={"url": st.column_config.LinkColumn("Original article"),
                                "published_at": st.column_config.TextColumn("Published (source)"),
                                "retrieved_at": st.column_config.TextColumn("Retrieved (local)")})
    st.caption("Published time comes from the source (blank if the source gave none — never invented). Sentiment is a "
               "simple lexicon score, shown for context only; signals are never generated from sentiment.")
    if len(v):
        pick = st.selectbox("Explain an item", v.index, format_func=lambda i: v.loc[i, "headline"][:110], key="nw_pick")
        item = v.loc[pick].to_dict()
        ask_ai_box("announcement", {"announcement": {k: item[k] for k in ("headline", "publisher", "published_at", "category", "url")}},
                   f"**{item['headline']}** — {item['publisher']}, category *{item['category']}*, relevance {item['relevance']}. "
                   f"{item['verification']}. Read the original: {item['url']}", "ai_news")


def _earnings_tab() -> None:
    st.markdown("**Skill 10 — Earnings Analyst.** Quarterly results from NSE/BSE filings (SEBI LODR), imported as CSV.")
    up = st.file_uploader("Results CSV (symbol, period_end, basis, revenue, ebitda, pat, eps)", type=["csv"], key="ea_up")
    if up and st.button("Import results", key="ea_imp"):
        try:
            st.success(f"{analyst.import_csv(up)} rows imported.")
        except Exception as e:
            st.error(str(e))
    syms = analyst.symbols()
    if not syms:
        st.info("No results imported. A template is in sample_data/results_template.csv.")
        return
    c = st.columns(2)
    s = c[0].selectbox("Company", syms, key="ea_sym")
    basis = c[1].radio("Basis", ["consolidated", "standalone"], horizontal=True, key="ea_basis")
    df = analyst.analyse(s, basis)
    if df.empty:
        st.warning(f"No {basis} figures for {s}.")
        return
    st.dataframe(df.drop(columns=["source"]), hide_index=True, use_container_width=True)
    fig = px.bar(df, x="period_end", y=["revenue", "pat"], barmode="group")
    st.plotly_chart(style(fig, 300, f"{s} revenue and PAT ({basis})"), use_container_width=True)
    st.caption("Informational. The reference defines no trading rule from earnings; use it to avoid results-day surprises.")


def _insider_tab() -> None:
    st.markdown("**Skill 11 — Insider & Bulk-Deal Tracker** (Indian substitute for the US Congress tracker). "
                "SEBI PIT insider disclosures, SAST, pledges, bulk and block deals, imported as CSV.")
    up = st.file_uploader("Disclosures CSV (kind, symbol, person, category, txn_type, qty, value, date)", type=["csv"], key="it_up")
    if up and st.button("Import disclosures", key="it_imp"):
        try:
            st.success(f"{insider_tracker.import_csv(up)} rows imported.")
        except Exception as e:
            st.error(str(e))
    df = insider_tracker.records()
    if df.empty:
        st.info("Nothing imported. Template: sample_data/disclosures_template.csv. Kinds: PIT, SAST, PLEDGE, BULK, BLOCK.")
        return
    held = [p["symbol"] for p in paper.positions()]
    flagged = insider_tracker.flag_held(held)
    if len(flagged):
        st.warning(f"{len(flagged)} disclosures involve instruments you hold in the paper account.")
        st.dataframe(flagged, hide_index=True, use_container_width=True)
    st.dataframe(df, hide_index=True, use_container_width=True, height=380)
    st.caption("Informational only: no signal is generated from disclosures until a backtest supports it.")


def render() -> None:
    st.title("News Intelligence")
    tabs = st.tabs(["📰 Announcements & news (skill 2)", "📊 Earnings analyst (skill 10)", "🕵️ Insider & bulk deals (skill 11)"])
    with tabs[0]:
        _news_tab()
    with tabs[1]:
        _earnings_tab()
    with tabs[2]:
        _insider_tab()
