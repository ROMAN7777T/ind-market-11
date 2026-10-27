"""Skill 11 - Insider & Bulk-Deal Tracker (Indian substitute for the Congress tracker).

The reference tracked US House STOCK Act disclosures; India has no equivalent for
legislators. The closest public data: SEBI PIT insider disclosures, SAST filings, promoter
pledges and NSE/BSE bulk and block deals, imported as CSV. Informational only: it does not
generate signals until a backtest shows otherwise.
"""
from __future__ import annotations

import pandas as pd

from .. import db

KINDS = ("PIT", "SAST", "PLEDGE", "BULK", "BLOCK")
COLUMNS = ["kind", "symbol", "person", "category", "txn_type", "qty", "value", "date"]


def import_csv(file, source: str = "Disclosure CSV") -> int:
    df = pd.read_csv(file)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in ("kind", "symbol", "date") if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}. Expected: {COLUMNS}")
    n = 0
    with db.session() as conn:
        for r in df.to_dict("records"):
            kind = str(r["kind"]).upper()
            if kind not in KINDS:
                raise ValueError(f"kind must be one of {KINDS}, got {kind}")
            conn.execute(
                "INSERT INTO insider (kind, symbol, person, category, txn_type, qty, value, date, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, str(r["symbol"]).upper(), r.get("person"), r.get("category"), r.get("txn_type"),
                 _f(r.get("qty")), _f(r.get("value")), pd.to_datetime(r["date"]).date().isoformat(), source))
            n += 1
    return n


def records(symbol: str | None = None) -> pd.DataFrame:
    if symbol:
        rs = db.rows("SELECT * FROM insider WHERE symbol = ? ORDER BY date DESC", (symbol.upper(),))
    else:
        rs = db.rows("SELECT * FROM insider ORDER BY date DESC LIMIT 1000")
    return pd.DataFrame(rs)


def flag_held(held_symbols: list[str]) -> pd.DataFrame:
    df = records()
    if df.empty:
        return df
    return df[df["symbol"].isin([s.upper() for s in held_symbols])]


def _f(v):
    try:
        x = float(v)
        return None if pd.isna(x) else x
    except (TypeError, ValueError):
        return None
