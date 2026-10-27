import io

import pytest

from terminal.news import core as news

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>ABC Ltd Q2 results: profit rises 12%</title><link>https://example.com/a</link>
<description>&lt;b&gt;Board&lt;/b&gt; approved results</description><pubDate>Tue, 20 Oct 2026 10:00:00 +0530</pubDate></item>
<item><title>SEBI issues circular on surveillance</title><link>https://example.com/b</link></item>
</channel></rss>"""


def test_parse_and_clean():
    items = news.parse_feed(RSS)
    assert len(items) == 2
    assert items[0]["published_at"].startswith("2026-10-20T10:00")
    assert items[1]["published_at"] is None  # never invented
    assert news.clean_text(items[0]["summary"]) == "Board approved results"


def test_entity_declarations_refused():
    with pytest.raises(ValueError):
        news.parse_feed(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss></rss>')


def test_dedupe_across_sources():
    items = [{"headline": "ABC Ltd Q2 results: profit rises 12%", "url": "https://a"},
             {"headline": "ABC LTD Q2 RESULTS - profit rises 12%", "url": "https://b"}]
    new, dup = news.store_items(items, "src", official=True)
    assert (new, dup) == (1, 1)
    assert news.store_items(items[:1], "src2", official=False) == (0, 1)


def test_classification_and_relevance():
    from terminal.data import instruments
    instruments.upsert([{"symbol": "ABC", "name": "ABC Industries", "segment": "EQ", "exchange": "NSE"}], "t")
    news.store_items(news.parse_feed(RSS), "NSE", official=True)
    df = news.items()
    row = df[df["headline"].str.startswith("ABC")].iloc[0]
    assert row["category"] == "results" and "ABC" in row["symbols"] and row["relevance"] == "HIGH"
    assert row["verification"].startswith("Official")
    assert row["retrieved_at"] and row["published_at"] != row["retrieved_at"]


def test_fetch_rate_limit_and_https(monkeypatch):
    class Resp:
        status_code = 200
        raw = None
        content = RSS

    class Sess:
        calls = 0

        def get(self, *a, **k):
            Sess.calls += 1
            return Resp()

    feed = {"name": "t", "url": "https://example.com/rss", "official": False}
    assert news.fetch_feed(feed, session=Sess())["ok"]
    second = news.fetch_feed(feed, session=Sess())
    assert not second["ok"] and "Rate limit" in second["message"] and Sess.calls == 1
    assert not news.fetch_feed({"name": "h", "url": "http://example.com"}, session=Sess(), force=True)["ok"]


def test_import_csv_keeps_missing_times_blank():
    f = io.StringIO("headline,url,published_at\nXYZ order win,https://x,\n")
    f.name = "a.csv"
    new, _ = news.import_file(f, "upload", False)
    assert new == 1
    assert news.items().iloc[0]["published_at"] is None
