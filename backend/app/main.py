"""FastAPI app: screens option chains and surfaces strategy ideas.

Endpoints:
  GET /api/health
  GET /api/strategies
  GET /api/screen?ticker=AAPL
  GET /api/scan?tickers=AAPL,MSFT&strategy=all|<strategy_key>

This app does not place trades or connect to a broker -- it is a research /
screening tool only. See README.md for the full disclaimer.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .models import ScreeningCriteria
from .providers import ProviderError, get_provider
from .screener import screen_chain
from .serializers import contract_to_dict, idea_to_dict, underlying_to_dict
from .strategies import all_strategies, get_strategy

app = FastAPI(title="Options Strategy Screener", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _criteria_from_query(min_oi: int | None, min_delta: float | None, min_dte: int | None) -> ScreeningCriteria:
    settings = get_settings()
    return ScreeningCriteria(
        min_open_interest=min_oi if min_oi is not None else settings.min_open_interest,
        min_abs_delta=min_delta if min_delta is not None else settings.min_abs_delta,
        min_days_to_expiration=min_dte if min_dte is not None else settings.min_days_to_expiration,
    )


def _parse_tickers(tickers: str) -> list[str]:
    symbols = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="Provide at least one ticker.")
    return symbols


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "data_provider": settings.data_provider}


@app.get("/api/strategies")
def list_strategies() -> dict:
    return {"strategies": [s.metadata() for s in all_strategies()]}


@app.get("/api/screen")
def screen(
    ticker: str = Query(..., description="Single ticker symbol, e.g. AAPL"),
    min_oi: int | None = Query(None, ge=0),
    min_delta: float | None = Query(None, ge=0, le=1),
    min_dte: int | None = Query(None, ge=0),
) -> dict:
    provider = get_provider()
    criteria = _criteria_from_query(min_oi, min_delta, min_dte)
    try:
        underlying = provider.get_underlying(ticker)
        chain = provider.get_option_chain(ticker, min_days_to_expiration=criteria.min_days_to_expiration)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    screened = screen_chain(chain, underlying, criteria)
    return {
        "underlying": underlying_to_dict(underlying),
        "criteria": {
            "min_open_interest": criteria.min_open_interest,
            "min_abs_delta": criteria.min_abs_delta,
            "min_days_to_expiration": criteria.min_days_to_expiration,
        },
        "contracts": [contract_to_dict(c) for c in screened],
    }


@app.get("/api/scan")
def scan(
    tickers: str = Query(..., description="Comma-separated ticker symbols, e.g. AAPL,MSFT"),
    strategy: str = Query("all", description="Strategy key, or 'all'"),
    min_oi: int | None = Query(None, ge=0),
    min_delta: float | None = Query(None, ge=0, le=1),
    min_dte: int | None = Query(None, ge=0),
) -> dict:
    provider = get_provider()
    criteria = _criteria_from_query(min_oi, min_delta, min_dte)

    if strategy == "all":
        strategies = all_strategies()
    else:
        found = get_strategy(strategy)
        if found is None:
            raise HTTPException(status_code=404, detail=f"Unknown strategy '{strategy}'.")
        strategies = [found]

    results = []
    for symbol in _parse_tickers(tickers):
        try:
            underlying = provider.get_underlying(symbol)
            chain = provider.get_option_chain(symbol, min_days_to_expiration=criteria.min_days_to_expiration)
        except ProviderError as exc:
            results.append({"symbol": symbol, "error": str(exc), "ideas": []})
            continue

        screened = screen_chain(chain, underlying, criteria)
        ideas = []
        for strat in strategies:
            for idea in strat.scan(symbol, underlying, screened):
                ideas.append(idea_to_dict(idea))
        results.append(
            {
                "symbol": symbol,
                "underlying": underlying_to_dict(underlying),
                "qualifying_contracts": len(screened),
                "ideas": ideas,
            }
        )

    return {
        "criteria": {
            "min_open_interest": criteria.min_open_interest,
            "min_abs_delta": criteria.min_abs_delta,
            "min_days_to_expiration": criteria.min_days_to_expiration,
        },
        "results": results,
    }


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
