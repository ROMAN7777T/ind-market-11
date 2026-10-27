"""The 11 skill modules from the reference, adapted for Indian markets.

| # | Reference skill            | Module                      |
|---|----------------------------|-----------------------------|
| 1 | Chart Scanner              | skills.scanner              |
| 2 | News Monitor               | news (package)              |
| 3 | Entry Timer                | skills.entry_timer          |
| 4 | Exit Planner               | skills.exit_planner         |
| 5 | Time Machine               | skills.time_machine         |
| 6 | Position Sizer (Budget)    | skills.sizer                |
| 7 | Risk Manager               | skills.risk                 |
| 8 | Order Desk (Broker)        | paper (paper broker ONLY)   |
| 9 | Price Alerts               | skills.alerts               |
| 10| Earnings Analyst           | skills.analyst              |
| 11| Congress Tracker           | skills.insider_tracker      |
"""

SKILLS = [
    (1, "Chart Scanner", "terminal.skills.scanner", "Scans stored charts for every enabled strategy and the reference's daily setups."),
    (2, "News Monitor", "terminal.news", "NSE/BSE/SEBI announcements and permitted feeds, deduplicated, with source links."),
    (3, "Entry Timer", "terminal.skills.entry_timer", "Watches an opening-range or level setup bar by bar: WAITING / TRIGGERED / EXPIRED."),
    (4, "Exit Planner", "terminal.skills.exit_planner", "Sets stop and target before entry; refuses bad plans."),
    (5, "Time Machine", "terminal.skills.time_machine", "10,000 bootstrap replays of the rest of the session plus the rule's own history."),
    (6, "Position Sizer", "terminal.skills.sizer", "Smallest of risk, position, cash, leverage and margin limits; lot rounding."),
    (7, "Risk Manager", "terminal.skills.risk", "Central gate for every paper entry; exits are never blocked."),
    (8, "Order Desk (paper only)", "terminal.paper", "Simulated orders with typed confirmation. No real broker order path exists."),
    (9, "Price Alerts", "terminal.skills.alerts", "Stop, target, flat-by and level alerts that ring once."),
    (10, "Earnings Analyst", "terminal.skills.analyst", "Quarterly results from imported NSE/BSE filings: margins, QoQ, YoY, TTM."),
    (11, "Insider & Bulk-Deal Tracker", "terminal.skills.insider_tracker", "Indian substitute for the Congress tracker: SEBI PIT, SAST, bulk/block deals."),
]
