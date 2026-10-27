"""News ingestion, deduplication and classification.

Article text is UNTRUSTED input: it is stripped of markup, length-capped, stored as data and
never interpreted as instructions. Sentiment is a simple optional lexicon score and is
never used to generate a trading signal.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd

from .. import db
from ..config import config_dir
from ..data import instruments
from ..timeutil import IST, now_ist

MAX_BYTES = 2_000_000
MIN_INTERVAL_S = 300  # per-feed polite rate limit
USER_AGENT = "IndQuantTerminal/1.0 (local research; respects robots and rate limits)"

CATEGORIES = [
    ("results", r"\b(results?|quarter|q[1-4]|earnings|profit|revenue|financial results)\b"),
    ("corporate action", r"\b(dividend|bonus|split|buyback|rights issue|record date)\b"),
    ("board meeting", r"\bboard meeting\b"),
    ("regulatory", r"\b(sebi|penalty|order|show cause|regulation|circular|surveillance|asm|gsm)\b"),
    ("deal / M&A", r"\b(acquisition|acquire|merger|amalgamation|stake|takeover|demerger)\b"),
    ("rating", r"\b(rating|upgrade|downgrade|crisil|icra|care ratings)\b"),
    ("insider / holding", r"\b(insider|promoter|pledge|sast|shareholding|bulk deal|block deal)\b"),
    ("macro", r"\b(rbi|repo|inflation|cpi|gdp|budget|fed|monetary policy|iip)\b"),
    ("management", r"\b(ceo|cfo|managing director|resign|appointment|director)\b"),
]
POS = {"profit", "growth", "record", "upgrade", "wins", "order win", "approval", "beats", "surge", "rises", "higher", "dividend", "bonus"}
NEG = {"loss", "decline", "downgrade", "penalty", "fraud", "default", "resign", "probe", "falls", "lower", "misses", "suspension", "pledge"}


def clean_text(s: str | None, limit: int = 500) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def story_id(headline: str) -> str:
    norm = re.sub(r"[^a-z0-9 ]", "", headline.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:20]


def categorize(text: str) -> str:
    t = text.lower()
    for name, pat in CATEGORIES:
        if re.search(pat, t):
            return name
    return "other"


def sentiment(text: str) -> str:
    t = text.lower()
    p = sum(w in t for w in POS)
    n = sum(w in t for w in NEG)
    if p == n:
        return "neutral (lexicon)"
    return ("positive" if p > n else "negative") + " (lexicon)"


def match_symbols(text: str) -> list[str]:
    t = text.upper()
    found = []
    for inst in instruments.all_instruments():
        sym = inst["symbol"]
        name = (inst.get("name") or "").upper()
        if re.search(rf"\b{re.escape(sym)}\b", t) or (len(name) > 5 and name.split(" (")[0] in t):
            found.append(sym)
    return found


def relevance(symbols: list[str], official: bool, category: str) -> str:
    if symbols and (official or category in ("results", "regulatory", "deal / M&A")):
        return "HIGH"
    if symbols or official:
        return "MEDIUM"
    return "LOW"


def store_items(items: list[dict], source: str, official: bool) -> tuple[int, int]:
    """Insert parsed items; returns (new, duplicates)."""
    new = dup = 0
    retrieved = now_ist().isoformat(timespec="seconds")
    with db.session() as conn:
        for it in items:
            headline = clean_text(it.get("headline"), 300)
            if not headline:
                continue
            sid = story_id(headline)
            if conn.execute("SELECT 1 FROM news WHERE id = ?", (sid,)).fetchone():
                dup += 1
                continue
            text = headline + " " + clean_text(it.get("summary"), 1000)
            syms = match_symbols(text)
            cat = categorize(text)
            conn.execute(
                """INSERT INTO news (id, headline, publisher, url, published_at, retrieved_at, symbols, category, sentiment,
                   relevance, source, verification) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, headline, clean_text(it.get("publisher"), 100) or source, (it.get("url") or "")[:500],
                 it.get("published_at"), retrieved, json.dumps(syms), cat, sentiment(text), relevance(syms, official, cat),
                 source, "Official exchange/regulator source" if official else "Third-party publisher (not verified)"))
            new += 1
    return new, dup


def parse_feed(content: bytes) -> list[dict]:
    """Parse RSS 2.0 or Atom. Entities are not expanded beyond the parser defaults."""
    if len(content) > MAX_BYTES:
        raise ValueError("Feed larger than 2 MB; refused")
    if b"<!ENTITY" in content[:5000]:
        raise ValueError("Feed declares XML entities; refused for safety")
    root = ET.fromstring(content)
    items = []
    for it in root.iter("item"):
        items.append({"headline": it.findtext("title"), "url": it.findtext("link"),
                      "summary": it.findtext("description"), "published_at": _date(it.findtext("pubDate"))})
    ns = "{http://www.w3.org/2005/Atom}"
    for e in root.iter(f"{ns}entry"):
        link = e.find(f"{ns}link")
        items.append({"headline": e.findtext(f"{ns}title"), "url": link.get("href") if link is not None else None,
                      "summary": e.findtext(f"{ns}summary"), "published_at": _date(e.findtext(f"{ns}updated"))})
    return items


def _date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(IST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        try:
            return pd.Timestamp(s).tz_convert(IST).isoformat()
        except Exception:
            return None  # never invent a timestamp


# ---------- feeds ----------

def feeds_path() -> Path:
    return config_dir() / "news_feeds.json"


def load_feeds() -> list[dict]:
    with open(feeds_path(), encoding="utf-8") as f:
        return json.load(f)["feeds"]


def save_feeds(feeds: list[dict]) -> None:
    with open(feeds_path(), encoding="utf-8") as f:
        data = json.load(f)
    data["feeds"] = feeds
    with open(feeds_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def fetch_feed(feed: dict, session=None, force: bool = False) -> dict:
    """Fetch one feed over HTTPS with a timeout and a per-feed rate limit."""
    import requests

    last = db.get_setting(f"newsfetch:{feed['name']}", 0)
    if not force and time.time() - float(last or 0) < MIN_INTERVAL_S:
        return {"feed": feed["name"], "ok": False, "message": f"Rate limit: wait {MIN_INTERVAL_S}s between fetches."}
    if not str(feed["url"]).startswith("https://"):
        return {"feed": feed["name"], "ok": False, "message": "Only https:// feeds are allowed."}
    http = session or requests
    try:
        r = http.get(feed["url"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"},
                     timeout=15, stream=True)
        db.set_setting(f"newsfetch:{feed['name']}", time.time())
        if r.status_code != 200:
            return {"feed": feed["name"], "ok": False, "message": f"HTTP {r.status_code} (source may block automated access)."}
        content = r.raw.read(MAX_BYTES + 1, decode_content=True) if hasattr(r, "raw") and r.raw else r.content
        items = parse_feed(content)
    except Exception as e:  # network or parse error: keep existing data
        return {"feed": feed["name"], "ok": False, "message": f"{type(e).__name__}: {str(e)[:200]}"}
    for it in items:
        it.setdefault("publisher", feed.get("publisher", feed["name"]))
    new, dup = store_items(items, feed["name"], bool(feed.get("official")))
    return {"feed": feed["name"], "ok": True, "message": f"{len(items)} items, {new} new, {dup} duplicates."}


def import_file(file, source: str, official: bool) -> tuple[int, int]:
    """Import announcements from CSV/JSON with columns: headline, url, published_at, publisher, summary."""
    name = getattr(file, "name", "")
    if str(name).lower().endswith(".json"):
        items = json.load(file)
    else:
        items = pd.read_csv(file).to_dict("records")
    for it in items:
        if it.get("published_at") is not None and not pd.isna(it.get("published_at")):
            try:
                ts = pd.Timestamp(it["published_at"])
                ts = ts.tz_localize(IST) if ts.tzinfo is None else ts.tz_convert(IST)
                it["published_at"] = ts.isoformat()
            except (ValueError, TypeError):
                it["published_at"] = None
        else:
            it["published_at"] = None
    return store_items(items, source, official)


def items(symbol: str | None = None, category: str | None = None, limit: int = 300) -> pd.DataFrame:
    rs = db.rows("SELECT * FROM news ORDER BY COALESCE(published_at, retrieved_at) DESC LIMIT ?", (limit * 3,))
    df = pd.DataFrame(rs)
    if df.empty:
        return df
    df["symbols"] = df["symbols"].apply(lambda s: json.loads(s) if s else [])
    if symbol:
        df = df[df["symbols"].apply(lambda s: symbol in s)]
    if category:
        df = df[df["category"] == category]
    return df.head(limit)
