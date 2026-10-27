# IndQuant Terminal

A local, browser-based research, backtesting and **paper-trading** terminal for the Indian market (NSE equities, NIFTY,
BANKNIFTY, index/stock futures and options where data exists). It runs only on this computer, at `http://localhost:8501`.

- **Kotak Neo is DISCONNECTED by default.** There is no automatic login, no background connection and no credential prompt.
- **No real orders.** The application has no code path to any broker's order endpoint. All trading is simulated.
- **All data stays local** unless you choose to host a copy (see Hosting online): SQLite database, Parquet market data, logs and exports live in this folder.
- **Strategies** follow the 11-skill reference (Cloud9 Markets / day-trader-skill), adapted for NSE, plus the strategies from the
  master build prompt. Full rules: [docs/strategy_specification.md](docs/strategy_specification.md).
- Nothing here is financial advice. Signals are rule matches. Backtests describe the past.

---

## Windows setup (PowerShell)

Open **PowerShell** in this folder (Shift + right-click the folder → *Open PowerShell window here*).

### 1. Check Python

```powershell
py -3.12 --version
```

You need Python 3.12 (3.11 also works). If the command fails, install Python from python.org and tick *Add python.exe to PATH*.

### 2. Create the virtual environment

```powershell
py -3.12 -m venv .venv
```

### 3. Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

(Or run `.\setup.ps1`, which does steps 2–6 for you. If PowerShell blocks scripts, run
`Set-ExecutionPolicy -Scope Process Bypass` in the same window first; it only lasts for that window.)

### 4. Configure the project

```powershell
Copy-Item .env.example .env
```

`.env` holds placeholders only. You do not need to fill anything to use the terminal. Never paste credentials into chat.

### 5. Initialise sample data

Start the app (step 7) and press **Generate simulated data** on the Overview page. This creates 12 synthetic instruments with a
`SIM_` prefix. Every screen labels them **SIMULATED**: they do not represent any real instrument or current market conditions.

### 6. Run the automated tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The tests use temporary folders, mocked services and no network. They never touch Kotak or your real data.

### 7. Launch the terminal

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address localhost
```

Easiest: double-click **`Start IndQuant Terminal.bat`** in this folder. Or run `.\start.ps1`. Then open
**http://localhost:8501** in Chrome or Edge (the start scripts open it for you). The server only listens on `localhost`.
Always run commands from inside this folder: from any other folder, PowerShell reports "term not recognized".

### 8. Stop the terminal

Press **Ctrl + C** in the PowerShell window, then close the browser tab.

### 9. Import historical CSV files

**Data Manager → Import candles.** Required columns: `timestamp, open, high, low, close, volume`
(template: `sample_data/candles_template.csv`). Timestamps without a time zone are read as IST. Intraday timestamps are **bar
start** times (09:15, 09:20, …). Every candle is validated. Invalid OHLC, duplicates and bars outside 09:15–15:30 are dropped and
reported, and missing bars are counted. Re-importing the same symbol merges new rows. Also import:

- **Instrument master** (tick size, lot size, expiry): required for F&O sizing. Template: `sample_data/instruments_template.csv`.
- **NSE holiday calendar** from the exchange's annual circular. Template: `sample_data/holidays_template.csv`.

### 10. Troubleshooting

| Problem | Fix |
|---|---|
| `py` not found | Install Python 3.12 from python.org with *Add to PATH*, reopen PowerShell. |
| `streamlit` not recognised | Use the full form `.\.venv\Scripts\python.exe -m streamlit run app.py`. |
| Port 8501 busy | `.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8502` |
| Browser did not open | Open http://localhost:8501 manually in Chrome or Edge. |
| "Holiday calendar not loaded" | Import the NSE holiday CSV in Data Manager → Holiday calendar. |
| A page says "No data yet" | Generate simulated data on Overview, or import CSVs in Data Manager. |
| Import rejected | Check the column names and that high ≥ open/close ≥ low; the error lists every problem. |
| Slow first scan | The first scan reads all datasets; later scans use cached data. |
| OneDrive sync warnings | The database lives in `data/`. If OneDrive locks it, pause syncing while the app runs. |

---

## Hosting online

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). A hosted copy requires a password, disables broker connections, and may lose
its data when the host restarts.

## Daily workflow

1. `.\start.ps1` → open http://localhost:8501.
2. **Advanced Chart Terminal**: 1/2/3/4-chart layouts, indicators, drawing tools, replay clock.
3. **Strategy Scanner → Scan results**: rule matches with entry trigger, stop, target, R:R, quality score and failure reasons.
4. **Strategy Scanner → Trade Desk**: the reference workflow (entry timer → exit plan → Time Machine → sizing → risk check →
   paper order with typed `CONFIRM`).
5. **Paper Trading**: step the replay clock, and watch stops, targets, flat-by and alerts. **Trade Journal**: review the results.
6. **Backtesting Lab**: costs, slippage, out-of-sample split and walk-forward.
7. **Settings & Connections**: connect Kotak only when you decide to (see [docs/KOTAK_INTEGRATION.md](docs/KOTAK_INTEGRATION.md)).

### The replay clock

Without a verified live feed, the terminal runs on a **replay clock** over stored data. Signals, prices, paper fills and alerts
use only bars that had **closed** by the clock time, so you can step through a past session bar by bar. The replay clock is
always labelled and is never presented as a live price.

## Data modes

| Mode | Meaning |
|---|---|
| `DISCONNECTED` | No data stored and no provider connected. |
| `SIMULATED` | Synthetic demo data (`SIM_` symbols). |
| `HISTORICAL` | Data you imported, replayed on the replay clock. |
| `LIVE` | Only after a verified provider connection with valid live data (not available yet). |

Simulated and historical data are never mixed in one dataset. A stale live feed never produces a fresh signal.

## Project layout

```
app.py                     Streamlit entry point (11 pages)
terminal/                  application package
  skills/                  the 11 reference skill modules (scanner, entry timer, exit planner, Time Machine, sizer,
                           risk, alerts, earnings analyst, insider tracker); news/ is skill 2; paper.py is skill 8
  strategies/              reference strategies + master-prompt strategies, registry
  data/                    validation, local store, instrument master, simulated data, data modes
  providers/               market-data provider interface, Kotak Neo stub (disconnected), WebSocket wrapper
  backtest.py costs.py indicators.py fno.py paper.py clock.py ai.py secure.py db.py models.py
  ui/                      theme, charts, shared widgets, pages/
config/                    cost model (unverified defaults: edit), news feeds (disabled by default)
docs/                      strategy specification, Kotak integration guide
tests/                     pytest suite
data/ logs/ exports/       created at runtime, local only
```

## Costs

`config/cost_model.json` holds default brokerage, STT, exchange, SEBI, stamp duty and GST assumptions. They are marked
**unverified**: rates change and differ by broker. Check them against your broker's current charge sheet before relying on any result.
