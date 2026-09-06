# Options

An options-strategy screener: it filters option chains down to liquid,
directional contracts and surfaces trade ideas modeled on well-known
options-trading strategies.

**This is a research/education tool, not a trading system.** It does not
place orders, connect to a brokerage, or manage a portfolio, and nothing here
is financial advice. Quotes, greeks, and payoff figures are estimates — verify
everything with your broker before acting on it.

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
    serializers.py       # dataclass -> JSON dict
    main.py             # FastAPI app + routes, serves frontend/
  tests/               # pytest, run entirely against the mock provider
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
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/ — the FastAPI app serves the frontend
directly, no separate server needed.

By default it runs against the mock provider. For live data:

```bash
DATA_PROVIDER=yfinance uvicorn app.main:app --reload
```

Other tunables (env vars, or per-request query params on `/api/screen` and
`/api/scan`): `MIN_OPEN_INTEREST`, `MIN_ABS_DELTA`, `MIN_DAYS_TO_EXPIRATION`.

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

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

Tests run entirely against `MockProvider`, so they don't require network
access and are deterministic.

## API

- `GET /api/health`
- `GET /api/strategies` — metadata for every strategy (name, attribution, description)
- `GET /api/screen?ticker=AAPL[&min_oi=&min_delta=&min_dte=]` — screened contracts for one ticker
- `GET /api/scan?tickers=AAPL,MSFT&strategy=all|<key>[&min_oi=&min_delta=&min_dte=]` — strategy ideas per ticker
