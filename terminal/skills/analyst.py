"""Skill 10 - Earnings Analyst.

Original: SEC EDGAR XBRL quarterly numbers, margins, QoQ/YoY, TTM. India: quarterly results
filed with NSE/BSE under SEBI LODR, imported as CSV (no scraping). Standalone and
consolidated figures are kept separate. Informational only: no trading rule.
"""
from __future__ import annotations

import pandas as pd

from .. import db

COLUMNS = ["symbol", "period_end", "basis", "revenue", "ebitda", "pat", "eps"]


def import_csv(file, source: str = "Results CSV") -> int:
    df = pd.read_csv(file)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in ("symbol", "period_end", "revenue", "pat") if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Expected: {COLUMNS}")
    if "basis" not in df.columns:
        df["basis"] = "consolidated"
    n = 0
    with db.session() as conn:
        for r in df.to_dict("records"):
            pe = pd.to_datetime(r["period_end"]).date().isoformat()
            conn.execute(
                """INSERT INTO earnings (symbol, period_end, basis, revenue, ebitda, pat, eps, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, period_end, basis) DO UPDATE SET revenue=excluded.revenue, ebitda=excluded.ebitda,
                   pat=excluded.pat, eps=excluded.eps, source=excluded.source""",
                (str(r["symbol"]).upper(), pe, str(r["basis"]).lower(), _f(r.get("revenue")), _f(r.get("ebitda")),
                 _f(r.get("pat")), _f(r.get("eps")), source))
            n += 1
    return n


def analyse(symbol: str, basis: str = "consolidated") -> pd.DataFrame:
    rs = db.rows("SELECT * FROM earnings WHERE symbol = ? AND basis = ? ORDER BY period_end", (symbol.upper(), basis))
    if not rs:
        return pd.DataFrame()
    df = pd.DataFrame(rs)
    df["ebitda_margin_pct"] = df["ebitda"] / df["revenue"] * 100
    df["pat_margin_pct"] = df["pat"] / df["revenue"] * 100
    for c in ("revenue", "pat", "eps"):
        df[f"{c}_qoq_pct"] = df[c].pct_change(fill_method=None) * 100
        df[f"{c}_yoy_pct"] = df[c].pct_change(4, fill_method=None) * 100
    df["revenue_ttm"] = df["revenue"].rolling(4, min_periods=4).sum()
    df["pat_ttm"] = df["pat"].rolling(4, min_periods=4).sum()
    df["eps_ttm"] = df["eps"].rolling(4, min_periods=4).sum()
    return df.round(2)


def symbols() -> list[str]:
    return [r["symbol"] for r in db.rows("SELECT DISTINCT symbol FROM earnings ORDER BY symbol")]


def _f(v):
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None
