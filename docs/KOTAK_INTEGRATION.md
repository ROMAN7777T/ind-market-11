# Connecting Kotak Neo later

**Current state:** the Kotak provider (`terminal/providers/kotak_neo.py`) is a disconnected stub. It never connects on
start-up, never runs in the background, and never sends anything to Kotak. Pressing **Connect Kotak** in Settings runs local
checks only: are the expected environment variables present, and is an SDK module installed. It then reports
`SETUP REQUIRED`.

**Order placement is permanently out of scope.** The provider interface (`terminal/providers/base.py`) has no order methods,
and a test (`tests/test_kotak_and_safety.py`) fails if any provider gains one. The paper engine (`terminal/paper.py`) imports no
provider or network code.

## What a future integration session must do (in order)

1. **Read the current official Kotak Neo API documentation.** Identify the supported Python SDK (package name, version, licence),
   the authentication flow, the session lifetime, and the rate limits. Do not rely on memory, forum posts or old examples.
2. **Confirm the account's permissions.** Which data is entitled (quotes, depth, historical candles, WebSocket streaming,
   instrument master, F&O), and whether historical data is available at all.
3. **Pin the SDK** in `requirements.txt` after verifying it installs on Windows with Python 3.12.
4. **Confirm the credential names** the documented flow needs. Update `REQUIRED_ENV` and `.env.example` (placeholders only).
   Secrets stay in `.env` or the OS keychain. They must never go into SQLite, logs, screenshots or chat.
5. **Implement `KotakNeoProvider.connect()`** with the documented flow, behind `user_initiated=True`. Store the session object in
   memory only. `disconnect()` must clear it.
6. **Add data methods one at a time**: instrument master → quotes → historical candles → WebSocket stream. For each, write mocked
   tests first (no live calls in the test suite). Then do a single manual, user-initiated check, and record the result in
   `info.capabilities`.
7. **Feed live data through validation.** Candles go through `terminal/data/validation.py`. Streams go through
   `ReconnectingStream`, which marks data STALE on interruption. Set `info.live_data = True` only when a verified feed is
   delivering fresh bars. Only then does the UI show `LIVE`.
8. **Respect SEBI's retail algorithmic-trading framework** and the broker's API terms (order-rate limits, registration,
   static IP), even for data-only use where they apply.
9. **Keep paper trading separate.** Live prices may drive the paper engine. Orders remain simulated.

## Where things plug in

| Concern | File |
|---|---|
| Provider interface (data only) | `terminal/providers/base.py` |
| Kotak implementation | `terminal/providers/kotak_neo.py` |
| Process-wide provider state | `terminal/providers/manager.py` |
| Reconnecting stream wrapper | `terminal/providers/stream.py` |
| Clock switches to LIVE automatically | `terminal/clock.py` (`is_live()` reads `live_data_ok()`) |
| Settings UI | `terminal/ui/pages/settings_page.py` |
| Secret loading and redaction | `terminal/secure.py` |

The dashboard, scanner, risk engine, backtester and paper engine do not need changes: they read from the store and the clock.
