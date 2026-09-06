# Options

An options-strategy screener with order placement: it filters option chains
down to liquid, directional contracts, surfaces trade ideas modeled on
well-known options-trading strategies, and can place orders against a
simulated paper account or (optionally, gated behind explicit configuration
and per-order confirmation) a real E*TRADE account.

**Nothing here is financial advice**, and quotes/greeks/payoff figures are
estimates — verify everything with your broker before acting on it. The app
places real orders **only** if you explicitly configure it to (see
[Auth & trading](#auth--trading) below); by default every order goes to a
simulated paper account and no real money is ever at risk.

## Screening criteria

Every option contract must clear all three filters before it can back a
strategy idea (configurable via query params or env vars, see below):

- **Open interest > 100** — avoids illiquid, hard-to-fill contracts.
- **|delta| >= 0.4** — favors contracts with meaningful directional exposure
  over deep out-of-the-money lottery tickets.
- **Expiration >= 14 days out** — avoids the extreme theta/gamma risk of the
  final one to two weeks before expiration.

Delta isn't part of a raw option quote, so the app computes it itself with the
Black-Scholes formula, using each contract's implied volatility, the
underlying's spot price, and a static risk-free rate assumption
(`app/greeks.py`).

## Strategies

Each strategy is attributed to the trading style/community that popularized
it (see `/api/strategies` or the UI for the full descriptions):

| Strategy | Style |
|---|---|
| Covered Call | Classic income overlay (tastytrade-style premium selling) |
| Cash-Secured Put | Premium-selling entry (tastytrade / "sell high-probability premium") |
| The Wheel | CSP → assignment → covered calls cycle (r/thetagang, tastytrade) |
| Poor Man's Covered Call | LEAPS/diagonal capital-efficient covered call |
| Bull Call Debit Spread | Defined-risk directional spread (tastytrade) |
| Bear Put Debit Spread | Defined-risk bearish spread (tastytrade) |
| Long Call | Deep-ITM stock-replacement / momentum play |
| Long Put | Deep-ITM stock-replacement bearish play / hedge |

Because every leg must independently clear the delta >= 0.4 filter, some of
these look more aggressive than how they're often taught (e.g. the short leg
of a credit spread or PMCC is usually much lower delta) — that's intentional,
per the screening requirement, and each strategy's rationale text says so
where relevant (see `poor_mans_covered_call.py`).

## Architecture

```
backend/
  app/
    models.py         # OptionContract, Underlying, ScreeningCriteria, StrategyIdea
    greeks.py          # Black-Scholes delta calculation
    screener.py         # applies ScreeningCriteria to a raw chain
    config.py            # env-driven settings
    providers/            # pluggable market data sources
      base.py               # MarketDataProvider interface
      mock_provider.py       # deterministic offline sample data (default)
      yfinance_provider.py   # live data via the `yfinance` package
    strategies/            # one module per strategy, self-registering
    auth.py               # PBKDF2 password hashing + signed session cookies
    db.py                  # sqlite3 persistence: orders, paper account, E*TRADE tokens
    trading/                 # pluggable brokers, mirrors providers/
      base.py                   # Broker interface
      paper_broker.py            # simulated fills against live quotes
      etrade_broker.py            # OAuth1 + real order placement (equity only)
    serializers.py       # dataclass -> JSON dict
    main.py             # FastAPI app + routes, serves frontend/
  scripts/
    create_admin.py     # generates ADMIN_USERNAME/ADMIN_PASSWORD_HASH/SECRET_KEY
  tests/               # pytest, run entirely against the mock provider + paper broker
frontend/
  index.html, app.js, styles.css   # vanilla JS UI, no build step
```

### Why a mock data provider?

Real option greeks (open interest, implied volatility) require a live market
data source. `yfinance` (free, no API key) is wired up for that, but it needs
outbound network access to Yahoo Finance, which isn't available in every
environment (e.g. this was built in a sandboxed session where that access is
blocked). The `MockProvider` generates a deterministic, realistic-shaped
option chain for a handful of symbols (AAPL, MSFT, NVDA, TSLA, SPY) so the
whole app — screener, strategies, API, UI, tests — can be developed and
verified end-to-end without network access, and demoed offline. Switch to
live data with `DATA_PROVIDER=yfinance` (see below).

## Running it

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/create_admin.py   # prints env vars auth needs -- see below
```

Export what it prints (plus `COOKIE_SECURE=false`, since local dev is plain
http, not https) before starting the server:

```bash
export ADMIN_USERNAME=... ADMIN_PASSWORD_HASH='...' SECRET_KEY=... COOKIE_SECURE=false
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/ and log in — the FastAPI app serves the
frontend directly, no separate server needed. Without those env vars set,
every route except `/api/health` returns `503`.

By default it runs against the mock provider. For live data:

```bash
DATA_PROVIDER=yfinance uvicorn app.main:app --reload
```

Other tunables (env vars, or per-request query params on `/api/screen` and
`/api/scan`): `MIN_OPEN_INTEREST`, `MIN_ABS_DELTA`, `MIN_DAYS_TO_EXPIRATION`.

### Deploying to a real server

See [`backend/deploy/CYBERPANEL.md`](backend/deploy/CYBERPANEL.md) for a
step-by-step guide to deploying on a CyberPanel (OpenLiteSpeed) VPS as a
systemd service behind a reverse proxy -- including the `options-app.service`
unit file in that same directory. A real VPS's outbound network path is
independent of any Claude Code Remote sandbox, so it's the environment to use
for a genuine live test of the `yfinance` provider.

## Testing the yfinance provider against live data

The `MockProvider` is what this repo's automated tests and the sandboxed
session it was built in exercise (Yahoo Finance is unreachable from that
sandbox's network policy). To verify the live path on a machine with normal
internet access:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/test_yfinance_live.py            # defaults to AAPL,MSFT,NVDA,TSLA,SPY
python3 scripts/test_yfinance_live.py AAPL GOOGL # or pass your own tickers
```

It fetches real quotes and option chains, runs them through the screener, and
exercises the full `/api/scan` HTTP path with `DATA_PROVIDER=yfinance`,
printing sample screened contracts and any errors. Exits non-zero on failure.

**Known result:** two separate Claude Code Remote environments both block
outbound access to Yahoo Finance (`query1/query2.finance.yahoo.com`,
`fc.yahoo.com`, `guce.yahoo.com` all reject the CONNECT tunnel with a 403 at
the proxy layer). The app itself degrades correctly under that failure —
`/api/scan` returns 200 with a per-symbol `error` field, `/api/screen`
returns 400 with a clear message, neither crashes — but real live-data
verification has to happen outside those sandboxes: a developer's own
machine, or a CI runner with unrestricted egress. Full evidence and raw
output from both attempts: [`backend/scripts/yfinance_live_test_report.md`](backend/scripts/yfinance_live_test_report.md).

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Tests run entirely against `MockProvider`, so they don't require network
access and are deterministic.

## Auth & trading

The whole app (everything except `/api/health`) requires logging in as a
single admin user — there's no public signup. Set it up:

```bash
cd backend
python3 scripts/create_admin.py
```

This prints `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, and `SECRET_KEY` env
vars to set before the app will serve anything but a 503. See
`backend/deploy/options-app.service` for where these go in production, or
export them directly for local dev.

**Order placement defaults to a paper (simulated) broker** — a virtual cash
balance and positions tracked in a local SQLite DB (`DB_PATH`, default
`options_app.db`), with fills simulated against live quotes. No real money
is ever at risk in this mode, and it needs no broker credentials.

**Real order placement via E*TRADE** is implemented but gated behind two
separate switches that must both be set (`ACTIVE_BROKER=etrade` and
`LIVE_TRADING_ENABLED=true`), plus a `confirm_live: true` flag the API
requires on every individual order request (the UI's confirm-by-typing
modal handles this for you). Getting there requires your own E*TRADE
developer account and OAuth setup — full walkthrough, including sandbox
testing before going live, in `backend/deploy/CYBERPANEL.md`'s
"Auth & trading setup" section. Read `backend/app/trading/etrade_broker.py`'s
module docstring first: it was built against E*TRADE's documented API but
could not be tested end-to-end in the sandbox that built it, and it only
supports single-leg equity orders (no options orders, no multi-leg spreads
— see that file for why).

## API

- `GET /api/health` — public
- `POST /api/auth/login`, `POST /api/auth/logout` — public
- `GET /api/auth/me` — auth required
- `GET /api/strategies` — metadata for every strategy (name, attribution, description); auth required
- `GET /api/screen?ticker=AAPL[&min_oi=&min_delta=&min_dte=]` — screened contracts for one ticker; auth required
- `GET /api/scan?tickers=AAPL,MSFT&strategy=all|<key>[&min_oi=&min_delta=&min_dte=]` — strategy ideas per ticker; auth required
- `GET /api/broker/status` — which broker is active and whether live trading is enabled; auth required
- `GET /api/account`, `GET /api/positions`, `GET /api/orders` — auth required
- `POST /api/orders` — place an order (paper by default; real E*TRADE orders need `confirm_live: true`); auth required
- `POST /api/orders/{id}/cancel` — auth required
- `GET /api/broker/etrade/auth-url`, `POST /api/broker/etrade/complete-auth` — E*TRADE OAuth setup; auth required
