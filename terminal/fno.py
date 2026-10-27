"""F&O analytics: option chains, Black-Scholes Greeks, implied volatility, basis, PCR, max pain.

Provider-supplied values and locally calculated estimates are kept in separate columns.
Greeks and IV are NOT calculated when an essential input is missing. Index candles are never
treated as option prices.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

from . import config, db
from .data.modes import DataMode
from .timeutil import IST

CHAIN_COLUMNS = ["strike", "option_type", "ltp", "bid", "ask", "oi", "oi_change", "volume", "iv"]


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _npdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_price(S, K, T, r, sigma, kind):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if kind == "CE":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def greeks(S, K, T, r, sigma, kind) -> dict:
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    delta = _ncdf(d1) if kind == "CE" else _ncdf(d1) - 1
    gamma = _npdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _npdf(d1) * math.sqrt(T) / 100
    if kind == "CE":
        theta = (-S * _npdf(d1) * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _ncdf(d2)) / 365
    else:
        theta = (-S * _npdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _ncdf(-d2)) / 365
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def implied_vol(price, S, K, T, r, kind, lo=1e-4, hi=5.0, tol=1e-6) -> float | None:
    """Bisection IV. Returns None when the price is outside no-arbitrage bounds."""
    if price is None or price <= 0 or T <= 0 or S <= 0:
        return None
    intrinsic = max(0.0, S - K * math.exp(-r * T)) if kind == "CE" else max(0.0, K * math.exp(-r * T) - S)
    if price < intrinsic - 1e-9:
        return None
    f_lo, f_hi = bs_price(S, K, T, r, lo, kind) - price, bs_price(S, K, T, r, hi, kind) - price
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f = bs_price(S, K, T, r, mid, kind) - price
        if abs(f) < tol:
            return mid
        if f * f_lo < 0:
            hi = mid
        else:
            lo, f_lo = mid, f
    return (lo + hi) / 2


def years_to_expiry(expiry: date, as_of: datetime, close: str = "15:30") -> float:
    h, m = (int(x) for x in close.split(":"))
    exp_dt = datetime.combine(expiry, time(h, m), IST)
    return max(0.0, (exp_dt - as_of).total_seconds() / (365 * 24 * 3600))


def enrich(chain: pd.DataFrame, spot: float | None, expiry: date, as_of: datetime, rate: float) -> pd.DataFrame:
    """Add locally calculated IV (if the provider gave none) and Greeks. Missing inputs -> NaN + reason."""
    df = chain.copy()
    T = years_to_expiry(expiry, as_of)
    df["iv_source"] = np.where(df["iv"].notna(), "provider", "")
    calc_iv, reasons = [], []
    for _, r in df.iterrows():
        if spot is None:
            calc_iv.append(np.nan)
            reasons.append("no underlying price")
            continue
        if T <= 0:
            calc_iv.append(np.nan)
            reasons.append("expired")
            continue
        if not pd.isna(r["iv"]):
            calc_iv.append(float(r["iv"]) / 100)
            reasons.append("")
            continue
        price = r["ltp"] if not pd.isna(r["ltp"]) else (
            (r["bid"] + r["ask"]) / 2 if not (pd.isna(r.get("bid")) or pd.isna(r.get("ask"))) else None)
        iv = implied_vol(price, spot, r["strike"], T, rate, r["option_type"]) if price else None
        calc_iv.append(iv if iv else np.nan)
        reasons.append("" if iv else "no valid option price")
    df["sigma"] = calc_iv
    df.loc[df["iv_source"] == "", "iv_source"] = np.where(pd.Series(calc_iv, index=df.index)[df["iv_source"] == ""].notna(),
                                                          "calculated (estimate)", "unavailable")
    df["calc_note"] = reasons
    for g in ("delta", "gamma", "theta", "vega"):
        df[g] = np.nan
    for i, r in df.iterrows():
        if spot and T > 0 and not pd.isna(r["sigma"]) and r["sigma"] > 0:
            for k, v in greeks(spot, r["strike"], T, rate, r["sigma"], r["option_type"]).items():
                df.at[i, k] = v
    df["iv_pct"] = df["sigma"] * 100
    if {"bid", "ask"} <= set(df.columns):
        mid = (df["bid"] + df["ask"]) / 2
        df["spread_pct"] = (df["ask"] - df["bid"]) / mid.replace(0, np.nan) * 100
    return df


def pcr(chain: pd.DataFrame) -> float | None:
    ce, pe = chain.loc[chain["option_type"] == "CE", "oi"].sum(), chain.loc[chain["option_type"] == "PE", "oi"].sum()
    return round(pe / ce, 2) if ce > 0 else None


def max_pain(chain: pd.DataFrame) -> float | None:
    if chain["oi"].isna().all():
        return None
    strikes = sorted(chain["strike"].unique())
    ce = chain[chain["option_type"] == "CE"].set_index("strike")["oi"]
    pe = chain[chain["option_type"] == "PE"].set_index("strike")["oi"]
    pain = {}
    for s in strikes:
        pain[s] = float(sum(max(0, s - k) * ce.get(k, 0) for k in ce.index) + sum(max(0, k - s) * pe.get(k, 0) for k in pe.index))
    return min(pain, key=pain.get) if pain else None


def basis(fut_price: float, spot: float, expiry: date, as_of: datetime) -> dict:
    T = years_to_expiry(expiry, as_of)
    b = fut_price - spot
    return {"basis": round(b, 2), "basis_pct": round(b / spot * 100, 3),
            "annualised_pct": round(b / spot / T * 100, 2) if T > 0 else None, "days_to_expiry": round(T * 365, 1)}


# ---------- storage ----------

def save_chain(underlying: str, expiry: str, as_of: str, df: pd.DataFrame, source: str, mode: DataMode) -> None:
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in ("strike", "option_type") if c not in df.columns]
    if missing:
        raise ValueError(f"Option chain needs columns {missing}. Expected: {CHAIN_COLUMNS}")
    for c in CHAIN_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df["option_type"] = df["option_type"].str.upper().str.strip()
    if not set(df["option_type"]) <= {"CE", "PE"}:
        raise ValueError("option_type must be CE or PE")
    d = config.data_dir() / "options"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{underlying}_{expiry}_{as_of.replace(':', '')}.parquet"
    df[CHAIN_COLUMNS].to_parquet(path, index=False)
    db.execute("""INSERT INTO option_chains (underlying, expiry, as_of, source, mode, path, rows) VALUES (?, ?, ?, ?, ?, ?, ?)
                  ON CONFLICT(underlying, expiry, as_of) DO UPDATE SET source=excluded.source, mode=excluded.mode,
                  path=excluded.path, rows=excluded.rows""",
               (underlying.upper(), expiry, as_of, source, mode.value, str(path), len(df)))


def chains() -> list[dict]:
    return db.rows("SELECT * FROM option_chains ORDER BY underlying, expiry, as_of DESC")


def load_chain(row: dict) -> pd.DataFrame:
    return pd.read_parquet(row["path"])


def simulate_chain(underlying: str, spot: float, as_of: datetime, step: float, n: int = 15, days: int = 7,
                   base_iv: float = 0.14, seed: int = 3) -> tuple[str, pd.DataFrame]:
    """SIMULATED option chain from Black-Scholes with a volatility smile. Not market data."""
    rng = np.random.default_rng(seed)
    expiry = (as_of + timedelta(days=days)).date()
    atm = round(spot / step) * step
    T = years_to_expiry(expiry, as_of)
    rows = []
    for k in range(-n, n + 1):
        K = atm + k * step
        m = math.log(K / spot)
        iv = base_iv + 0.8 * m * m + (-0.05 * m)
        for kind in ("CE", "PE"):
            px = max(0.05, bs_price(spot, K, T, 0.065, iv, kind))
            spread = max(0.05, px * 0.01)
            oi = float(max(0, rng.normal(1, 0.3)) * 1e5 * math.exp(-abs(k) / 6) * (1.3 if (kind == "PE") == (k < 0) else 1))
            rows.append({"strike": K, "option_type": kind, "ltp": round(px / 0.05) * 0.05, "bid": round((px - spread / 2) / 0.05) * 0.05,
                         "ask": round((px + spread / 2) / 0.05) * 0.05, "oi": round(oi), "oi_change": round(oi * rng.normal(0, 0.1)),
                         "volume": round(oi * abs(rng.normal(0.5, 0.2))), "iv": np.nan})
    return expiry.isoformat(), pd.DataFrame(rows)
