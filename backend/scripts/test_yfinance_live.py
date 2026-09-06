#!/usr/bin/env python3
"""Smoke-test the yfinance provider against real, live market data.

Run this on a machine with normal internet access (this repo was built in a
sandboxed session whose network policy blocks Yahoo Finance directly, so this
path could only be tested with mock data there).

Usage:
    cd backend
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python3 scripts/test_yfinance_live.py [TICKER ...]

With no arguments it tests AAPL, MSFT, NVDA, TSLA, and SPY. Exits non-zero if
any stage fails.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Force live data regardless of any DATA_PROVIDER already in the environment.
os.environ["DATA_PROVIDER"] = "yfinance"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"]


def main() -> int:
    tickers = sys.argv[1:] or DEFAULT_TICKERS
    failures = 0

    print(f"Testing yfinance provider with: {', '.join(tickers)}\n")

    # --- Stage 1: provider layer directly -----------------------------------
    from app.providers import ProviderError
    from app.providers.yfinance_provider import YFinanceProvider
    from app.screener import screen_chain
    from app.models import ScreeningCriteria

    provider = YFinanceProvider()
    criteria = ScreeningCriteria()  # OI > 100, |delta| >= 0.4, DTE >= 14

    for symbol in tickers:
        print(f"--- {symbol} ---")
        try:
            underlying = provider.get_underlying(symbol)
            print(f"  quote: ${underlying.price:.2f} (dividend yield {underlying.dividend_yield:.2%})")
        except ProviderError as exc:
            print(f"  FAILED to fetch quote: {exc}")
            failures += 1
            continue

        try:
            chain = provider.get_option_chain(symbol, min_days_to_expiration=criteria.min_days_to_expiration)
            print(f"  raw chain: {len(chain)} contracts across expirations >= {criteria.min_days_to_expiration} days out")
        except ProviderError as exc:
            print(f"  FAILED to fetch option chain: {exc}")
            failures += 1
            continue

        if not chain:
            print("  WARNING: chain came back empty (no expirations, or all filtered by min_days_to_expiration)")

        screened = screen_chain(chain, underlying, criteria)
        print(f"  screened (OI > {criteria.min_open_interest}, |delta| >= {criteria.min_abs_delta}): {len(screened)} contracts qualify")

        deltas_present = [c.delta for c in chain if c.delta is not None]
        if chain and not deltas_present:
            print("  WARNING: no contract in the raw chain got a delta computed -- check implied_volatility values")

        for c in sorted(screened, key=lambda c: (c.expiration, c.strike))[:3]:
            print(
                f"    sample: {c.expiration} ${c.strike:g} {c.option_type.value.upper()} "
                f"delta={c.delta:.2f} OI={c.open_interest} IV={c.implied_volatility:.2f} mid=${c.mid_price:.2f}"
            )
        print()

    # --- Stage 2: full API path via FastAPI TestClient -----------------------
    print("--- Full API path (FastAPI TestClient, DATA_PROVIDER=yfinance) ---")
    try:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        health = client.get("/api/health").json()
        print(f"  /api/health -> {health}")
        assert health["data_provider"] == "yfinance"

        tickers_param = ",".join(tickers[:2])
        resp = client.get("/api/scan", params={"tickers": tickers_param, "strategy": "all"})
        print(f"  GET /api/scan?tickers={tickers_param}&strategy=all -> HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(f"    body: {resp.text[:500]}")
            failures += 1
        else:
            body = resp.json()
            for result in body["results"]:
                if "error" in result and result["error"]:
                    print(f"    {result['symbol']}: ERROR {result['error']}")
                    failures += 1
                else:
                    print(f"    {result['symbol']}: {len(result['ideas'])} idea(s), {result['qualifying_contracts']} qualifying contracts")
    except Exception as exc:  # noqa: BLE001 - report and count as failure, don't crash the summary
        print(f"  FAILED: {exc}")
        failures += 1

    print()
    if failures:
        print(f"DONE with {failures} failure(s). See output above.")
        print(
            "If you saw connection/certificate errors: this machine needs outbound HTTPS access to "
            "query1.finance.yahoo.com and query2.finance.yahoo.com."
        )
        print(
            "If quotes/chains fetched fine but nothing ever screens in: markets may be closed with a thin "
            "chain, or try a more liquid ticker/lower --min-delta via the API's min_delta param."
        )
    else:
        print("All checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
