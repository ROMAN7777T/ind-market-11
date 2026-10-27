# Strategy Specification — Indian-Market AI Trading Terminal

**Status:** Implemented in IndQuant Terminal v1.0 (research, backtesting and paper trading only). See §18 for the implementation map. No broker connection, no real orders. None of the strategies has been validated on Indian market data.
**Date:** 2026-10-27
**Reference:** Cloud9 Markets, "Claude's Free Day-Trading Desk" — https://www.cloud9markets.com/day-trader-skill.html
**Secondary reference:** the open-source `day-trader-skill` pack v2.0.0 (MIT, by Jake Schincariol) that the page describes. Its rule documentation (`SKILL.md` files) was read for concepts and parameters. No source code was copied.

---

## 0. Read this first: what the "11" actually are

**The reference does not describe 11 trading strategies.** It describes **11 skills**: tools in one long-only US day-trading workflow ("Eleven skills. Eleven jobs."). Only two of them generate trade signals. The rest find candidates, plan exits, run simulations, size positions, manage risk, route orders, send alerts or do research.

Across the whole reference, there are **six signal setups** with explicit rules, plus a "level" entry mode:

| # | Setup | Where it's defined | Type |
|---|---|---|---|
| A | Opening-range breakout (ORB), 15-min range | Scanner + Entry Timer | Intraday entry |
| B | 20-day closing-high breakout (`breakout_20d`) | Scanner (daily) | Pre-market watchlist filter |
| C | Bull flag (`bull_flag`) | Scanner (daily) | Pre-market watchlist filter |
| D | Reclaim of 20-day average (`reclaim_ma20`) | Scanner (daily) | Pre-market watchlist filter |
| E | Oversold, RSI(14) < 30 (`oversold`) | Scanner (daily) | Pre-market watchlist filter |
| F | Oversold bounce (`oversold_bounce`) | Scanner (daily) | Pre-market watchlist filter |
| — | Level breakout (close above a user-given level) | Entry Timer | Intraday entry mode |

Setups B–F only **produce a watchlist**. The reference gives them **no entry, stop or exit rules of their own**. They feed the intraday entry (ORB, or a level such as the 20-day high). In the original, every trade is long-only, intraday, and closed by 15:55 ET.

**How this document is organised:** Sections 2–12 specify the 11 skills as "strategy modules", because the user asked for 11. For each one, I mark whether it is a **signal strategy** or a **support module**. I have **not invented** five extra strategies to reach 11. Section 13 lists the six signal setups as standalone strategy cards for the terminal.

### Labelling convention
- **[ORIGINAL]**: stated in the reference (web page or pack documentation).
- **[ADAPT-IN]**: my proposed Indian-market adaptation. It is not in the reference and must be validated.
- **[GAP]**: the reference is silent or incomplete here.

---

## 1. Global framework

### 1.1 Original framework [ORIGINAL]
- Market: US-listed common stocks, ordinary shares and ADRs (≈5,940 symbols from Nasdaq Trader directories; ETFs, warrants, units, rights, preferreds and notes excluded).
- Session: NYSE 09:30–16:00 ET. Early close at 13:00 is handled. 2026/2027 holiday calendars are included.
- Direction: **long only**. No shorts, options, margin, leverage or crypto unless config allows it and the user confirms.
- Data: free, unofficial, delayed Yahoo Finance (5-min and 1-min bars, daily closes), Nasdaq symbol lists, SEC EDGAR, House Clerk. No API key.
- Workflow order: Scanner → News → Entry → Exit → Time Machine → Budget → Risk → Broker (+ Alerts, Analyst, Congress tracker as side tools).
- Only **closed bars** count. A wick or the live tick never triggers anything.
- Paper trading is the default. Every order needs a typed "yes" plus a second confirmation.
- Default limits: budget $5,000; cash buffer 10%; max loss/trade $50; max daily loss $150; max 3 trades/day; min reward:risk 1.0; stop required; no entries before 09:45 or after 15:30; flat by 15:55; max position 75%; max order $4,000; min order $5.
- The reference's own evidence (see §14): the ORB + Time Machine combination **did not show an edge** in its test. The author says the tool helps screen out bad trades, but did not show that it picks winners. Costs and slippage were excluded.

### 1.2 Indian-market framework [ADAPT-IN]
| Item | Original (US) | Proposed India adaptation |
|---|---|---|
| Exchange / session | NYSE 09:30–16:00 ET | NSE cash & F&O, normal market **09:15–15:30 IST**. Pre-open call auction 09:00–09:08 (equities). Times in IST (no DST). |
| Holidays | NYSE 2026/27 list | NSE trading-holiday calendar, loaded per year from the exchange circular. Handle special/Muhurat sessions as non-standard days (no auto-trading). |
| Universe | US common stocks + ADRs | Configurable: (a) NSE F&O stocks, (b) NIFTY 200/500 constituents, (c) indices NIFTY 50 and NIFTY BANK. Exclude series other than `EQ`/`BE` (as configured), ETFs, SME, and stocks in the **F&O ban list** (for F&O trades), **ASM/GSM** surveillance, or with trading suspended. |
| Price/liquidity floor | ≥ $5, ≥ 1M shares/day | Proposed: price ≥ ₹50, 20-day average traded value ≥ ₹25 crore (tunable). |
| Instruments | Stocks (long) | Phase 1: NSE equity long (intraday/MIS or delivery/CNC). Phase 2: index & stock **futures** (long). Phase 3: **long options** (buy CE for long signals) on NIFTY/BANKNIFTY. Option selling is out of scope. |
| Indices | n/a | NIFTY and BANKNIFTY **cannot be traded directly**. Generate the signal on the spot index (or the near-month future) and execute in futures or options. |
| Tick size / lots | 1 cent | Read tick size and lot size from the broker/exchange **instrument master** each day. Never hardcode them (NSE revises both). Round stops away from entry to the instrument tick. |
| Price bands | n/a | Respect daily price bands / circuit limits. Skip a stock within 2% of its band. Refuse a stop beyond the band. |
| Entry window | 09:45–15:30 ET | Proposed: **no entries before 09:30 IST** (after a 15-min ORB) and **none after 14:45 IST**. |
| Flat-by | 15:55 ET | Proposed **15:10 IST**, which is before typical broker MIS auto square-off (≈15:15–15:25, broker-specific; read from config). |
| Expiry | n/a | NIFTY weekly + monthly and BANKNIFTY monthly contracts. The expiry weekday has changed several times under SEBI/NSE rules, so **read it from the instrument master**, never hardcode. Proposed default: no new option entries on expiry day after 13:00. |
| Short selling | Blocked | Keep long-only for Phase 1 (same as the original). Intraday shorts are legal in India but untested here. See §15. |
| PDT rule | FINRA PDT guard | Not applicable. Replace it with margin checks: MIS/peak-margin requirement ≤ available margin, plus a cap on leverage used. |
| Costs | Excluded in reference | **Must be included** in every backtest and in the Time Machine R calculation: brokerage, STT/CTT, exchange transaction charges, SEBI fee, stamp duty, GST, plus a slippage assumption (proposed: 1 tick + 0.03% for liquid stocks; wider for options). |
| Risk defaults (INR) | $ values | Proposed for a ₹1,00,000 account: cash buffer 10%; max loss/trade ₹500 (0.5%); max daily loss ₹1,500; max 3 trades/day; min R:R 1.5; stop required; max position 50%; max order ₹50,000; min order ₹1,000. |
| Data source | Yahoo, free/delayed | Broker market-data API (later phase, not now) for live 1/5-min bars, plus a historical store (≥ 60 sessions of 5-min bars; ≥ 1 year of daily). Free delayed sources can be used for research only. |

---

## 2. Module 1 — Chart Scanner (`trader-scanner`) — *signal generator (candidates)*

**Purpose [ORIGINAL]:** It scans thousands of charts and lists those that match a rule. It explicitly says "matched a rule", never "a buy".

### 2.1 Original rules [ORIGINAL]
**Universe build:** about weekly, from Nasdaq Trader symbol directories. Keep common/ordinary/ADR/units of trust. Drop test issues, ETFs, warrants, SPAC units and rights, notes/ETNs, preferreds and % coupons.

**Daily (pre-market) scan.** It uses daily **closes only**, with liquidity of last price ≥ $5 and last-session volume ≥ 1,000,000:

| Setup | Rule |
|---|---|
| `breakout_20d` | Last close > every close of the prior 20 sessions |
| `bull_flag` | Up > 10% over the 10 sessions before the last 5, then last 5 closes within a 5% range |
| `reclaim_ma20` | Previous close < its 20-day SMA, last close > its 20-day SMA |
| `oversold` | RSI(14), Wilder smoothing, < 30 |
| `oversold_bounce` | RSI(14) < 30 yesterday **and** today closed up |

Hits are ranked by traded value (price × volume). The scan must run before the open or after the close, because mid-session volume is partial.

**Intraday ORB scan** (after 09:50 ET):
- Opening range = first 15 minutes = the 09:30, 09:35 and 09:40 five-minute bars. Range high = highest high, range low = lowest low.
- Hit = **first completed 5-min bar that CLOSES above the range high**, stamped at that bar's close time.
- Two stages. Stage 1 is a cheap pre-filter on closes. Stage 2 confirms with real highs/lows, capped at 200 most-traded candidates, and reports PARTIAL if capped.
- A chart is usable only if **every** 5-min bar from the open to the cutoff exists. A missing bar means a halt or a thin stock, and the chart is skipped.
- Expires after `no_entries_after` (15:30). Prints nothing before 09:50, on weekends/holidays or after the close.

**Reporting rules:** always state how many symbols were scanned, returned and usable, and the data time. Never print P&L. A hit is stale once price moves on, so re-run before acting.

### 2.2 Indian adaptation [ADAPT-IN]
- Universe: from the NSE equity list / instrument master. Filter by series, F&O eligibility, index membership, and ASM/GSM/ban lists.
- Liquidity: price ≥ ₹50, previous-day traded value ≥ ₹25 cr (tunable).
- ORB window: **09:15–09:30 IST** (bars 09:15, 09:20, 09:25). The ORB scan runs from 09:35 IST.
- Pre-open: ignore the 09:00–09:08 auction prints for range-building. Log the pre-open gap % as a feature.
- Indices: run ORB on NIFTY 50 and NIFTY BANK spot (and/or near-month futures). Use spot for signal and futures volume for the volume check (spot indices have no volume).
- Gap filter (new, needs testing): flag stocks gapping more than ±3% versus the previous close. ORB behaviour on large gaps differs.
- Results-day filter: tag stocks with board meetings/results today (from NSE corporate announcements).

### 2.3 Data / timeframes / indicators
Daily OHLCV (≥ 40 sessions; 1 year preferred), 5-min OHLCV intraday, symbol master, surveillance/ban lists. Indicators: 20-day closing high, SMA(20), RSI(14) Wilder, 10-session % change, 5-session close range, opening-range high/low.

### 2.4 Suitability
ORB scan: **intraday**. Daily setups: **pre-market watchlist** in the original. They are swing candidates only in a proposed adaptation (§13).

---

## 3. Module 2 — News Monitor (`trader-news`) — *support / filter*

**Purpose [ORIGINAL]:** It tracks headlines and filings for watched stocks and flags what moves them.

**Original rules [ORIGINAL]:** Yahoo Finance headlines per ticker. SEC 8-K filings (earnings, CEO changes, deals, restatements, bankruptcy). Distance from yesterday's close. Shows only new items since the last check, newest first, tagged (earnings, analyst, deal, halt, regulatory, macro…) and never repeated. It is used after the scanner and before the entry. The Time Machine says to check news because "earnings, news and halts can do things those 60 days never did."

**[GAP]:** the reference defines no automatic block rule based on news. It is informational only.

**Indian adaptation [ADAPT-IN]:**
- Sources: NSE and BSE corporate announcements (board meetings, results, outcomes, dividends/splits/bonus, insider (PIT) disclosures, pledges, credit ratings), exchange surveillance notices, and SEBI orders. Add reputable Indian financial news feeds where licensing permits.
- Macro calendar: RBI policy dates, Union Budget, CPI/IIP releases, US Fed/CPI (big NIFTY impact), F&O expiry days.
- **Proposed filter (needs testing):** no new entry in a stock on its results day until 30 minutes after the results announcement. No index entries in the 15 minutes around RBI policy.

**Data:** announcement feeds (polling), corporate-actions calendar, event calendar. **Suitability:** both intraday and swing (as a filter).

---

## 4. Module 3 — Entry Timer (`trader-entry`) — *signal strategy (entry)*

**Purpose [ORIGINAL]:** It turns a setup into one moment, the bar that confirms it. It never buys.

### 4.1 Original rules [ORIGINAL]
- **Setups:** `orb` (level = 15-min opening-range high) or `level` (a user-given price, e.g. the 20-day high from the scanner).
- **Bars:** 5-min (default) or 1-min.
- **Trigger:** the **first completed bar after the range that CLOSES strictly above the level**. A wick above does not count. A close equal to the level does not count. There is one trigger per setup per day, and later closes do not reset it.
- **Entry price / time:** the trigger bar's close and close time.
- **Optional volume filter:** `--min-volume-x K` means trigger-bar volume ≥ K × the average volume of the range bars. The reference notes that 1.0 is already strict, because the first bar contains the opening auction.
- **Time limits:** no entries before 09:45 or after 15:30 ET. On early-close days the cutoff is 12:30.
- **States:** WAITING (with distance to level), TRIGGERED, EXPIRED, NO DATA, NOT OPEN, RANGE FORMING, CLOSED.
- **Stale-trigger rule:** if the trigger is more than one bar old, say so, because "a late entry is a different trade."
- Long only. Hand off to Exit Planner **before** anything is bought.

### 4.2 Invalidation [ORIGINAL + GAP]
- Expired if no trigger by `no_entries_after`.
- **[GAP]:** the reference has no rule to cancel the setup if price first breaks *below* the range low. **[ADAPT-IN] proposal:** invalidate the long ORB if a bar closes below the range low before any trigger (needs testing).

### 4.3 Indian adaptation [ADAPT-IN]
- Range: 09:15–09:30 IST. Earliest entry is the close of the 09:30 bar (09:35). No entries after 14:45.
- Volume filter: for stocks, use exchange volume. For indices, use near-month futures volume. Proposed default K = 1.0 for stocks, off for spot index.
- Execution mapping:
  - Equity: buy at market/limit = trigger close + tolerance (proposed ≤ 0.1% or 2 ticks). Skip if the live price has run more than 0.3% beyond the trigger close.
  - Futures: the same trigger on the futures (or spot) chart. Use whole lots only.
  - Options: on a long trigger, buy an ATM or 1-strike-ITM CE of the nearest non-expiry-day weekly (NIFTY) or monthly (BANKNIFTY). Levels stay on the underlying (see §6.3).
- Price-band check: refuse an entry if the stock is within 2% of its upper circuit.

**Data:** live 1/5-min bars with correct bar-close timestamps (IST), futures volume for indices. **Indicators:** opening-range high/low, volume ratio. **Suitability:** **intraday**.

---

## 5. Module 4 — Exit Planner (`trader-exit`) — *exit rules for every signal*

**Purpose [ORIGINAL]:** It sets the stop and target **before** entry, so nobody decides mid-move.

### 5.1 Original rules [ORIGINAL]
| Stop rule | Placement |
|---|---|
| `or-mid` (ORB default) | Opening-range midpoint = (OR high + OR low)/2 |
| `or-low` | Opening-range low (wider, so fewer shares) |
| `price:X` | User price |
| `pct:X` | X% below entry |
| `atr:K` | K × ATR(14) on the session's bars up to the entry bar. If there are fewer than 14 bars, it averages all of them and says so |

- A level setup has no opening range, so it **requires a user-named stop**.
- Rounding: the stop is rounded **away** from entry (down for a long). Target = entry + R × risk, rounded half-up.
- Targets: **2R default**, or 1R, 1.5R or `price:X`. Risk = entry − stop.
- **Refusals:** a stop at or above entry; a target at or below entry; risk < 0.05% of price (too tight for the spread); entry not triggered; shorts.
- **Flat by 15:55 ET** (12:55 on early close). Out regardless of P&L, no overnight hold. An entry at or after flat-by is refused.
- **Never move a stop further from entry** once the trade is on. Never widen a stop to make a plan pass.

### 5.2 Exit conditions summary [ORIGINAL]
1. Stop hit, giving −1R (a gap can fill worse).
2. Target hit, giving +R.
3. Time exit at flat-by, closing at market.

**[GAP]:** no trailing stop, no break-even move and no partial exits are defined.

### 5.3 Indian adaptation [ADAPT-IN]
- Flat-by **15:10 IST** (configurable, and always before the broker's auto square-off).
- Minimum risk: max(0.05% of price, 3 × tick size, the estimated round-trip cost × 3). The stop distance must clearly exceed costs.
- Futures: R computed in ₹ per lot = (entry − stop) × lot size.
- **Options (needs testing):** stop and target are defined on the **underlying**. When the underlying hits its level, exit the option at market. Add a premium-based hard stop (proposed: −40% of premium) as a backstop. Delta, IV crush and theta mean option R ≠ underlying R. The option's max loss = premium × qty (capped).
- Price bands: if the target is beyond today's upper band, cap the target at the band minus 1 tick, and re-check R:R.
- Optional extensions, each requiring backtesting before use: move the stop to break-even at +1R; partial exit at 1R, the remainder at 2R.

**Data:** entry record, OR levels, intraday bars (ATR), tick and lot size. **Indicators:** OR mid/low, ATR(14) intraday. **Suitability:** intraday. A swing variant would need different exits (see §13).

---

## 6. Module 5 — Time Machine (`trader-timemachine`) — *pre-trade validation filter*

**Purpose [ORIGINAL]:** It replays the rest of the day 10,000 times before you risk money, and reruns the rule on every past session.

### 6.1 Original method [ORIGINAL]
1. **Pool:** only FULL sessions before the plan date (all 78 five-minute bars, 09:30–16:00). Half days, gapped data and today are excluded. Each bar is stored as 4 ratios (O/H/L/C ÷ previous close). About 60 days are used, with a minimum of 20 full sessions.
2. **One replay:** start at the entry price. For each remaining bar, draw a random past bar from the same time of day (±2 bars) and scale it. Check the stop first, then the target. **A bar touching both counts as stop.**
3. **10,000 replays** give odds of target-first, stop-first, neither (open at `--until`, default the close; use flat-by), and green (target or above entry at `--until`). R = +R at target, −1 at stop, otherwise (price at until − entry)/risk. A gap through the stop counts as −1R (real fills can be worse).
4. **History:** the same rule (same OR, stop rule, target R) is run on every past session in the pool. This is what actually happened.
5. **Verdict:** among replays that hit a side, compare the target-first share with break-even = 1/(1+R) (50% at 1R, 33% at 2R, 25% at 3R). Within 5 points → "coin flip / close to break-even". 5–15 points → "Leans toward target/stop". ≥ 15 points → "Strongly toward". Extra lines appear when > 40% of replays hit neither, or when the sign of average R contradicts the lean.
6. Fixed seed (19) for reproducibility. The seed is reported.
- Refuses: < 20 full sessions, entry bar not in data, nonsensical plan, entry off the 5-min grid.
- If history and simulation disagree, say so. "Trust neither blindly."

### 6.2 Indian adaptation [ADAPT-IN]
- A full NSE session = **75 five-minute bars** (09:15–15:30). The pool needs ≥ 20 full sessions. Proposed ≥ 60.
- `--until` = flat-by (15:10).
- Deduct **round-trip costs** (in R units) from every replay's R. This is not in the original.
- Separate pools (needs testing): expiry days vs non-expiry days for indices, and results days excluded for stocks.
- Gap-risk realism: sample overnight gaps only if a swing variant is ever simulated (the original never holds overnight).
- **Options:** the replay runs on the underlying. Mapping the result to option P&L needs a delta/IV model. **The reference provides none.** Treat option odds as underlying odds only until a model is validated.
- Use as a **filter** (skip "Leans/Strongly toward stop"), not as a signal. That matches the reference's conclusion.

**Data:** ≥ 60 sessions of clean 5-min OHLC per instrument. **Suitability:** intraday plans only.

---

## 7. Module 6 — Position Sizer (`trader-budget`) — *risk control*

### 7.1 Original rules [ORIGINAL]
Whole shares = **min** of four limits:
1. Max loss: `max_loss_per_trade` ÷ risk per share.
2. Position cap: budget × `max_position_pct` ÷ entry.
3. Max order: `max_order` ÷ entry.
4. Cash: (budget − cash buffer) ÷ entry, never more than actual cash.

- Size at the **higher** of the plan entry and a fresh (< 15 min) price. A run-up shrinks the size, and a lower price never shrinks risk.
- Refuse (no order) if: 0 shares; below min order; R:R < min; stop not below entry; target not above entry (move already happened); plan from another day; blocked ticker; short.
- Output: one bracket order (market entry, stop-loss, take-profit), with the deciding limit stated.
- A stop too far away for the max loss is a **refusal, not a smaller order**.

### 7.2 Indian adaptation [ADAPT-IN]
- Currency ₹. Quantity is whole shares (equity) or **whole lots** (F&O). If 1 lot's risk > max loss/trade, refuse. Do not trade a fraction.
- Add a 5th limit, **margin**: qty × required margin per unit (MIS/NRML from the broker margin API) ≤ available margin × (1 − buffer).
- Options: risk per lot = min(premium × lot, underlying-stop-mapped loss). Use the premium as the hard worst case.
- Include estimated costs in max-loss: qty × risk + round-trip costs ≤ max loss.
- Bracket orders: Indian brokers' bracket/cover order availability varies, and is often withdrawn. **Design for separate SL-M + target limit orders managed by the terminal (OCO logic), with a server-side SL always placed.**

---

## 8. Module 7 — Risk Manager (`trader-risk`) — *risk control / hard gate*

### 8.1 Original checks [ORIGINAL]
Applied to every order in file order, as if earlier ones filled:
format; asset (no options/crypto unless allowed); short (no selling more than held); blocked list; size (min/max order); position %; cash buffer / no margin; **stop required** and on the correct side; **loss** (qty × (entry − stop) ≤ max loss/trade); **reward:risk ≥ min**; **daily loss** (sum of max-loss-at-stop of all today's entries, win or lose, + this one ≤ daily limit); **max trades/day**; **entry window** and market open; PDT guard (optional); **duplicate** (same symbol + side twice, or already placed today); max orders/day.
- **Exits are never blocked** by day limits, the window or size rules (warnings only). Getting out must always be possible.
- Measures risk from the higher of plan entry and a fresh (< 15 min) price.
- Verdicts are fingerprinted per exact order. Any edit means re-check. Yesterday's PASS is invalid today.
- Warnings: live account, stop only in the plan and not at the broker, stale price, early close.
- Never changes a limit itself.

### 8.2 Indian adaptation [ADAPT-IN]
Keep every original check, converted to ₹/IST, and add:
- F&O ban list, ASM/GSM, trading suspended, price-band proximity, and illiquid strike (option bid-ask spread > 2% of premium, or OI below a threshold).
- Margin check (replaces PDT). Leverage cap (proposed ≤ 2× for MIS in Phase 1).
- Expiry-day rule for options. No naked option selling (hard block in Phase 1–3).
- Kill switch: halt new entries for the day after daily loss used ≥ limit, or after 2 consecutive stop-outs (proposed, needs testing).
- Correlation cap: at most 1 open position per index (NIFTY spot, NIFTY futures and NIFTY options count as one exposure). BANKNIFTY and bank-heavy stocks are treated as correlated.
- Server-side stop required: warn → **block** if the stop-loss order is not accepted at the exchange within N seconds of entry fill (proposed).

---

## 9. Module 8 — Order Desk (`trader-broker`) — *execution (out of scope now)*

**Original [ORIGINAL]:** Sends approved orders to a broker (Alpaca/IBKR), paper by default. It shows a plain ticket and exact JSON, records the user's typed "yes" verbatim, then requires a second platform confirmation. It builds the flatten ticket at flat-by, records fills, and logs each trade's max loss for daily-limit accounting. Only places an order if the Risk Manager passed that exact order today, the user typed yes, and the tool approval was given. Keys live in env vars, never in chat.

**Indian adaptation [ADAPT-IN] — specification only, nothing built, no Kotak connection now:**
- Broker adapter interface (to be implemented later against the Kotak Neo API or others). Paper/simulated broker as default.
- Order types to map: MARKET, LIMIT, SL, SL-M. Product codes: intraday (MIS) vs delivery/normal.
- Same two-step human approval. Fingerprint match with the Risk Manager verdict. The flatten order is always allowed.
- Credentials: environment variables / OS keychain only. Never logged, never in the database, never in prompts.
- Respect SEBI's retail algo-trading framework (broker-registered algos, order-rate limits, static IP requirements where applicable). Confirm the current requirements with the broker before any live use.

---

## 10. Module 9 — Price Alerts (`trader-alerts`) — *support / exit monitoring*

**Original [ORIGINAL]:** It turns a plan into three alerts (stop, target, flat-by time). It also offers above/below levels, % move from the previous close, time-of-day and opening-bell alerts. Each rings **once** (unless re-armed). Plan alerts are dated, so yesterday's stop never rings today. Flat-by moves earlier on early-close days. Quotes are delayed. Prices are written to a prices file with timestamps, used by sizing and risk only if < 15 min old. An alert is a fact, never an order.

**Indian adaptation [ADAPT-IN]:** IST clock with the NSE holiday calendar. Alerts at 09:15 open, 15:10 flat-by, and broker auto-square-off warning time. Use a live broker/websocket feed when available (a later phase). Add alerts for OI change/IV spike on option positions and for upper/lower circuit proximity. **Suitability:** intraday (and swing monitoring).

---

## 11. Module 10 — Earnings Analyst (`trader-analyst`) — *research / filter*

**Original [ORIGINAL]:** Reads SEC EDGAR XBRL company facts (10-Q/10-K) and the earnings 8-K. Summarises revenue, gross/operating/net margins, net income and diluted EPS quarter by quarter, year-over-year, with TTM. It reads a pasted call transcript and flags whether the company reports this week. **[GAP]:** it defines no trading rule from these numbers.

**Indian adaptation [ADAPT-IN]:** Source quarterly results from NSE/BSE financial-results filings (XBRL where available) under SEBI LODR. Metrics: revenue, EBITDA and margin, PAT, EPS, YoY/QoQ, TTM. Note standalone vs consolidated. Results calendar from board-meeting intimations. Use as a **filter** (avoid intraday entries around results; a swing context feature). **Suitability:** swing/positional context. For intraday, only the "results today" flag.

---

## 12. Module 11 — Congress Tracker (`trader-pelosi`) — *alternative data (no direct Indian equivalent)*

**Original [ORIGINAL]:** Monitors US House STOCK Act Periodic Transaction Reports. Alerts once per new filing. Parses who, owner, ticker, buy/sell, option details, trade date, amount range and disclosure lag. Flags trades in held stocks. **[GAP]:** it defines no trading rule.

**Indian adaptation [ADAPT-IN]:** India has no equivalent public trade-by-trade disclosure for legislators. The closest public data are:
- **Insider trading disclosures** (SEBI PIT Regulations: promoter/director/KMP trades, via NSE/BSE).
- **SAST disclosures** (substantial acquisitions), **promoter pledge** changes.
- **Bulk and block deals** (daily, NSE/BSE).
Proposed module: "Insider & Bulk-Deal Tracker". It is informational only and has **no trading rule** until backtested. **Suitability:** swing/positional context only. **Needs testing** before it influences any signal.

---

## 13. Standalone strategy cards (the six setups)

Each card states what the reference defines and what is proposed. "Exit" defaults to Module 4 unless stated otherwise.

### S-A. Opening-Range Breakout (ORB) — **intraday**
- **Purpose:** catch early-session momentum when price closes above the first-15-minute high.
- **Market condition [ORIGINAL]:** any. The scanner ranks by liquidity. **[GAP]:** no trend or regime filter.
- **Entry [ORIGINAL]:** the first completed 5-min (or 1-min) bar after the range closing **strictly above** the OR high, within the entry window. Optional volume ≥ K × average OR-bar volume.
- **Stop [ORIGINAL]:** OR midpoint (default), or OR low / % / ATR(14)×K / price.
- **Target [ORIGINAL]:** 2R (default) or 1R/1.5R/price. **Time exit:** flat-by.
- **Filters [ORIGINAL]:** price ≥ $5, full bar set (no halts), entry window, news check, Time Machine verdict.
- **Invalidation [ORIGINAL]:** no trigger by the entry cutoff → expired. Trigger more than 1 bar old → flagged as a different trade.
- **India [ADAPT-IN]:** OR 09:15–09:30 IST. Entries 09:35–14:45. Flat 15:10. Works for NSE stocks, NIFTY/BANKNIFTY futures, and long CE options (levels on the underlying). Proposed extra filters: invalidate if a close < OR low happens before the trigger; skip if OR width > 1.5 × 20-day average OR width or < 0.3 × it; gap filter ±3%; skip results days and expiry-day afternoons.
- **Data:** 5-min (and/or 1-min) OHLCV intraday, futures volume for indices. **Indicators:** OR high/low/mid, volume ratio, ATR(14).
- **Testing need: HIGH.** The reference's own test showed 24 NVDA trades → −$239 at $50 risk each, with 0 favourable verdicts.

### S-B. 20-Day Closing-High Breakout — **pre-market filter (original); intraday level entry or swing (proposed)**
- **Original rule:** last daily close > all closes of the prior 20 sessions. It is a watchlist tag only. The Entry Timer can then use a level, e.g. the 20-day high, with a **user-named stop**.
- **[GAP]:** no defined stop or target for this setup. The level value (closing vs intraday high) for the entry is left to the user.
- **India [ADAPT-IN]:**
  - Intraday: level = previous 20-day high. Entry on a 5-min close above it after 09:30. Stop = ATR(14, 5-min) × 1.5 or the day's low. Target 2R. Flat 15:10.
  - Swing (new, not in reference): entry next day at a close above the level. Stop = 2 × daily ATR(14) or below the 10-day low. Exit on a close below SMA(20) or target 3R, max hold 10 sessions. Delivery (CNC) only. Gap risk applies.
- **Data:** daily OHLCV ≥ 40 sessions. **Indicators:** 20-day closing high, ATR(14). **Testing need:** HIGH (all exits are proposed).

### S-C. Bull Flag — **pre-market filter (original); swing (proposed)**
- **Original rule:** gain > 10% over the 10 sessions before the last 5, then the last 5 closes within a 5% range. Closes only.
- **[GAP]:** the reference does not state the denominator for the "5% range" (proposed: (max − min)/min of the 5 closes). No entry, stop or target.
- **India [ADAPT-IN]:** entry = daily close above the flag high (swing), or a 5-min close above the flag high intraday. Stop = flag low. Target = 2R, or a measured move (pole height) to be tested. Max hold 10 sessions. Add a volume filter: volume contraction during the flag (proposed).
- **Data:** daily OHLCV. **Indicators:** 10-session % change, 5-session range. **Testing need:** HIGH.

### S-D. Reclaim of 20-Day Average — **pre-market filter (original); swing (proposed)**
- **Original rule:** previous close < SMA(20), last close > SMA(20).
- **[GAP]:** no entry, stop, target or trend filter.
- **India [ADAPT-IN]:** entry next session above the reclaim-day high. Stop = reclaim-day low or SMA(20) − 1 × ATR. Exit on a close back below SMA(20), or 2R. Optional regime filter: NIFTY above its own SMA(50).
- **Data:** daily OHLCV. **Indicators:** SMA(20), ATR(14). **Testing need:** HIGH. Prone to whipsaw in sideways markets.

### S-E. Oversold (RSI(14) < 30) — **pre-market filter (original); swing mean-reversion (proposed)**
- **Original rule:** RSI(14), Wilder smoothing, < 30. The reference treats it as a scan tag, not a buy signal.
- **[GAP]:** no entry, stop or exit. An oversold stock can stay oversold. This tag is not a trade by itself.
- **India [ADAPT-IN]:** do not trade the tag alone. Use it only as the precondition for S-F. Proposed context filter: price above SMA(200) (buying dips in uptrends), excluding stocks with negative corporate news.
- **Data:** daily closes. **Indicators:** RSI(14) Wilder, SMA(200). **Testing need:** HIGH.

### S-F. Oversold Bounce — **pre-market filter (original); swing mean-reversion (proposed)**
- **Original rule:** RSI(14) < 30 yesterday **and** today's close > yesterday's close.
- **[GAP]:** no entry, stop or exit.
- **India [ADAPT-IN]:** entry next session above the bounce-day high. Stop = the lowest low of the last 5 sessions. Exit when RSI(14) > 50, or at 1.5R, or after a max of 7 sessions. The intraday variant uses the Entry Timer `level` = previous day high, with flat-by 15:10.
- **Data:** daily OHLCV. **Indicators:** RSI(14) Wilder. **Testing need:** HIGH. Catching-falling-knife risk.

### Intraday vs swing summary
| Strategy / module | Original | Proposed India use |
|---|---|---|
| S-A ORB | Intraday | Intraday (equity, index futures, long CE) |
| S-B 20D breakout | Watchlist → intraday level | Intraday level **and** swing (proposed) |
| S-C Bull flag | Watchlist | Swing primarily; intraday level optional |
| S-D MA20 reclaim | Watchlist | Swing |
| S-E Oversold | Watchlist | Precondition only |
| S-F Oversold bounce | Watchlist | Swing; intraday level optional |
| Exit, Time Machine, Sizer, Risk, Alerts | Intraday | Intraday (swing versions need new specs) |
| News, Analyst, Insider tracker | Context | Context / filters for both |

---

## 14. Evidence in the reference (do not overlook)

**[ORIGINAL]** The author tested NVDA, 31 Aug–23 Oct 2026, with a 15-min ORB, OR-midpoint stop, 2R target and exit by 15:55. The test used no look-ahead.
- 24 breakouts: 12 stop, 2 target, 10 neither. Taking all of them at $50 risk = **−$239**. The Time Machine flagged **0** as favourable.
- 12 large caps: **267 breakouts, only 7 "go" signals**. Stop-leaning trades lost on average. Break-even ones were roughly flat.
- Conclusion: the tool screens out bad trades but did not show that it picks winners. The sample is small. Costs and slippage were excluded.

**Implication for this terminal:** ORB with these defaults is **not a proven edge**. In India, adding STT, charges and slippage makes this worse. Implement it as a research/backtest strategy first.

---

## 15. Items that need additional testing before implementation

1. **ORB (S-A)** on NSE: OR length (15 vs 30 min), stop rule (mid vs low vs ATR), target (1R/1.5R/2R), volume filter, gap filter, with costs. Run per segment: large-cap stocks, NIFTY futures, BANKNIFTY futures.
2. **All daily setups (S-B…S-F):** the reference gives **no exits**. Every swing exit above is my proposal and must be backtested (≥ 3 years of daily data, walk-forward, with costs).
3. **Options execution:** underlying-level stops mapped to option premiums, strike selection, IV/theta effects, expiry-day behaviour. None of this is in the reference.
4. **Time Machine on NSE data:** check calibration (do "leans target" plans actually win at the stated rate?), with costs deducted, and expiry vs non-expiry pools.
5. **Short side** (intraday shorts, PE buying): not in the reference. A mirror-image ORB needs its own test.
6. **Kill switch, correlation cap, margin limit:** new risk rules. Verify that they behave correctly in simulation.
7. **Insider/bulk-deal tracker:** any predictive use is unproven.
8. **News/results filters:** the timing thresholds are guesses.
9. **Data quality:** bar-timestamp alignment (bar open vs close, IST), missing bars, corporate-action adjustment of daily history (splits/bonus), and index-future rollover.
10. **Order handling:** behaviour when SL orders are rejected, partial fills, freeze-quantity limits, and broker auto square-off timing.

**Proposed acceptance gate (before any paper trading):** out-of-sample, after costs, ≥ 100 trades per strategy/segment, positive expectancy, max drawdown within budget. Then ≥ 4 weeks of paper trading with matching results (the reference itself advises "a few weeks" on paper).

---

## 16. Data requirements summary

| Data | Granularity / history | Used by |
|---|---|---|
| Instrument master (symbol, series, tick, lot, expiry, strike) | Daily refresh | All |
| NSE holiday calendar / session times | Yearly | All time logic |
| Intraday OHLCV | 1-min and 5-min; ≥ 60 sessions stored, live during session | ORB, Entry, Exit (ATR), Time Machine |
| Daily OHLCV (adjusted) | ≥ 1 year (3+ for backtests) | Daily setups, liquidity filter |
| Index futures OHLCV + OI | Intraday & daily | Index ORB volume, futures execution |
| Option chain (LTP, bid/ask, OI, IV) | Live snapshot | Option execution, liquidity checks |
| Surveillance lists (ASM/GSM), F&O ban list, price bands | Daily | Scanner, Risk |
| Corporate announcements, results calendar, corporate actions | Polled intraday | News, Analyst, filters |
| Insider (PIT), SAST, bulk/block deals | Daily | Insider tracker |
| Broker positions, margin, fills | Live (later phase) | Sizer, Risk, Broker, Alerts |
| Cost schedule (brokerage, STT, charges, GST, stamp) | Config, updated on regulation change | Backtest, Time Machine, Sizer |

## 17. Indicator list
Opening-range high/low/midpoint · volume ratio vs OR average · ATR(14) (intraday and daily) · SMA(20), SMA(50)/SMA(200) (proposed regime filters) · RSI(14) Wilder · 20-day closing high · 10-session % change · 5-session close range · previous close / gap % · Monte Carlo odds and average R (Time Machine).

---

---

## 18. Implementation record (v1.0, 2026-10-27)

### 18.1 Decision on the "11 strategies" gap
The reference contains 11 *skills*, not 11 strategies (§0). The user chose: **build all 11 skills as separate modules; implement
the reference setups with the original rules where they exist; give the five daily setups the PROPOSED exits from §13, labelled
and disabled by default until backtested; and add the master-prompt strategies as a separate, labelled group.**
Deviation: **Oversold (S-E)** stays a watchlist tag with no trades, as §13 specified ("precondition only").

### 18.2 The 11 skill modules in code
| # | Skill | Module | Where in the UI |
|---|---|---|---|
| 1 | Chart Scanner | `terminal/skills/scanner.py` | Strategy Scanner → Scan results, Daily setups |
| 2 | News Monitor | `terminal/news/core.py` | News Intelligence → Announcements |
| 3 | Entry Timer | `terminal/skills/entry_timer.py` | Strategy Scanner → Trade Desk |
| 4 | Exit Planner | `terminal/skills/exit_planner.py` | Trade Desk |
| 5 | Time Machine | `terminal/skills/time_machine.py` | Trade Desk |
| 6 | Position Sizer | `terminal/skills/sizer.py` | Trade Desk, paper automation |
| 7 | Risk Manager | `terminal/skills/risk.py` (central engine) | Every paper entry; Risk monitor tab |
| 8 | Order Desk | `terminal/paper.py` (**paper only**) | Paper Trading, Trade Desk |
| 9 | Price Alerts | `terminal/skills/alerts.py` | Paper Trading → Alerts |
| 10 | Earnings Analyst | `terminal/skills/analyst.py` | News Intelligence → Earnings |
| 11 | Insider & Bulk-Deal Tracker (Congress-tracker substitute) | `terminal/skills/insider_tracker.py` | News Intelligence → Insider |

### 18.3 Strategy registry (`terminal/strategies/registry.py`)
| ID | Name | Source | Styles / timeframes | Default | Trades |
|---|---|---|---|---|---|
| REF_ORB | Opening-Range Breakout | Reference (original rules, NSE hours) | intraday 5m/1m | on | yes |
| REF_BREAKOUT20 | 20-Day Closing-High Breakout | Reference tag + proposed exits | swing 1d | **off** | yes |
| REF_BULLFLAG | Bull Flag | Reference tag + proposed exits | swing 1d | **off** | yes |
| REF_RECLAIM20 | Reclaim of 20-Day Average | Reference tag + proposed exits | swing 1d | **off** | yes |
| REF_OVERSOLD | Oversold (RSI < 30) | Reference tag | swing 1d | on | tag only |
| REF_OVERSOLD_BOUNCE | Oversold Bounce | Reference tag + proposed exits | swing 1d | **off** | yes |
| T_VWAP_RETEST | VWAP Breakout and Retest | Master prompt | intraday 5m/15m | on | yes |
| T_EMA_TREND | EMA Trend Continuation | Master prompt | intraday 5m/15m, swing 1d | on | yes |
| T_PULLBACK | Trend Pullback | Master prompt | intraday 15m, swing 1d | on | yes |
| T_RVOL_BREAKOUT | Relative Volume Breakout | Master prompt | intraday 5m/15m, swing 1d | on | yes |
| T_SWING_TREND | Swing Trend Continuation | Master prompt | swing 1d | on | yes |
| T_MEAN_REVERSION | Mean Reversion (Bollinger) | Master prompt | intraday 15m, swing 1d | **off (until tested)** | yes |

"Opening Range Breakout", item 1 of the master-prompt list, is the same implementation as REF_ORB. The exact rules of every
master-prompt strategy are shown in the app (Strategy Scanner → Strategy library) and in `terminal/strategies/terminal_set.py`.
They are **not** from the reference and are untested.

### 18.4 Indian-market defaults used in code (all editable in Settings)
Session 09:15–15:30 IST (pre-open 09:00–09:08) · ORB range 09:15–09:30 · entries 09:30–14:45 · flat-by 15:10 · risk per trade
0.5% · max open risk 1.5% · max daily loss 1.5% of start-of-day equity · max 3 positions · max 3 entries/day · min R:R 1.5 ·
stop required · max position 50% · cash buffer 10% · leverage 1× · shorts off · paper capital ₹1,00,000 · slippage 0.03% +
1 tick per fill · costs from `config/cost_model.json` (unverified defaults).

### 18.5 Signal quality score (scanner)
0–100 = data (0–25: 25 × (1 − missing-bar share of the latest session); 0 if stale) + trend (25 if the signal agrees with the
higher-timeframe EMA20/50 trend, 12 if sideways or unknown, 0 if opposed) + volume (25 × clip((relative volume − 0.5) / 1.5, 0, 1);
0 when volume is unavailable) + reward:risk (25 × min(R / 3, 1)). The score is a data and context check, not a probability.

### 18.6 Safeguards implemented
Signals are decided on bar close and filled at the next open with adverse, tick-rounded slippage. A bar touching both stop and
target counts as the stop. A gap through the stop fills at the open. Intraday trades never hold overnight. Costs are charged
on both legs. There is an in-sample / out-of-sample split and anchored walk-forward. A look-ahead test runs on every strategy.
Triggers older than one bar are reported as "TRIGGERED EARLIER" (a late entry is a different trade). A stale live feed
produces no fresh signal.

### 18.7 Still open (from §15)
- No strategy has been validated on real NSE data; all show "not tested".
- The intraday "level" variant of the daily setups exists only as a manual Entry Timer level, not as a scanner strategy.
- Option strategies cannot be backtested without imported historical contract prices. Underlying-to-option mapping is not modelled.
- The news timing filters (results day, RBI policy) are shown as information, not enforced as blocks.
- The cost model and the NSE holiday calendar must be verified and imported by the user.

*Educational specification. Not financial advice. Most day traders lose money. Nothing here has been backtested on real Indian
market data or connected to a broker.*
