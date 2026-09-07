"""FastAPI app: screens option chains, surfaces strategy ideas, and places
paper or (optionally, gated) live orders.

Endpoints:
  GET  /api/health                          (public)
  POST /api/auth/login, /api/auth/logout    (public)
  GET  /api/auth/me                         (auth required)
  GET  /api/strategies                      (public)
  GET  /api/screen?ticker=AAPL              (public)
  GET  /api/scan?tickers=AAPL,MSFT&...      (public)
  GET  /api/public/quote?symbol=AAPL        (public)
  GET  /api/public/history?symbol=&range=   (public)
  GET  /api/public/news?symbols=AAPL,MSFT   (public)
  GET  /api/public/level2?symbol=AAPL       (public; clearly-labeled simulated data)
  GET  /api/broker/status                   (auth required)
  GET  /api/account, /api/positions         (auth required)
  GET  /api/orders, POST /api/orders        (auth required)
  POST /api/orders/{id}/cancel              (auth required)
  GET  /api/broker/etrade/auth-url          (auth required)
  POST /api/broker/etrade/complete-auth     (auth required)

The screener/research/scanner endpoints are public -- they surface ideas, not
money. Only the trading module (account, orders, broker connection) requires
the admin login. Trading defaults to a paper (simulated) broker. Real order
placement only happens if BOTH ACTIVE_BROKER=etrade AND LIVE_TRADING_ENABLED=true
are set, and even then every order requires an explicit confirm_live=true in
the request body -- see app/trading/__init__.get_broker() and README.md.
"""
from __future__ import annotations

import random
import time
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .auth import clear_session_cookie, require_auth, set_session_cookie, verify_password
from .config import get_settings
from .models import ScreeningCriteria
from .providers import ProviderError, get_provider
from .screener import screen_chain
from .serializers import (
    account_to_dict,
    contract_to_dict,
    idea_to_dict,
    order_to_dict,
    position_to_dict,
    underlying_to_dict,
)
from .strategies import all_strategies, get_strategy
from .trading import BrokerError, OrderRequest, get_broker
from .trading.etrade_broker import ETradeBroker

app = FastAPI(title="Options Strategy Screener", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    settings = get_settings()
    db.init_db(settings.paper_starting_cash)


def _criteria_from_query(min_oi: Optional[int], min_delta: Optional[float], min_dte: Optional[int]) -> ScreeningCriteria:
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


def _is_live() -> bool:
    settings = get_settings()
    return settings.active_broker == "etrade" and settings.live_trading_enabled


# --- Auth ------------------------------------------------------------------


class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response) -> dict:
    settings = get_settings()
    if not settings.admin_username or not settings.admin_password_hash or not settings.secret_key:
        raise HTTPException(
            status_code=503,
            detail="Auth is not configured. See scripts/create_admin.py.",
        )
    if body.username != settings.admin_username or not verify_password(body.password, settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    set_session_cookie(response, body.username)
    return {"status": "ok", "username": body.username}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    clear_session_cookie(response)
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(username: str = Depends(require_auth)) -> dict:
    return {"username": username}


# --- Health ------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "data_provider": settings.data_provider}


# --- Screener / strategies (auth required) ------------------------------------


@app.get("/api/strategies")
def list_strategies() -> dict:
    return {"strategies": [s.metadata() for s in all_strategies()]}


@app.get("/api/screen")
def screen(
    ticker: str = Query(..., description="Single ticker symbol, e.g. AAPL"),
    min_oi: Optional[int] = Query(None, ge=0),
    min_delta: Optional[float] = Query(None, ge=0, le=1),
    min_dte: Optional[int] = Query(None, ge=0),
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
    min_oi: Optional[int] = Query(None, ge=0),
    min_delta: Optional[float] = Query(None, ge=0, le=1),
    min_dte: Optional[int] = Query(None, ge=0),
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


# --- Public market data: quotes, history, news, simulated level 2 ---------------
#
# These back the public site's News, Watchlist, Research, and Level 2 sections.
# None of them touch money or orders, so none require login.


@app.get("/api/public/quote")
def public_quote(symbol: str = Query(..., description="Ticker symbol, e.g. AAPL")) -> dict:
    provider = get_provider()
    try:
        return provider.get_quote_detail(symbol.strip().upper())
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


_VALID_RANGES = {"1D", "5D", "1W", "1M", "1Y"}


@app.get("/api/public/history")
def public_history(
    symbol: str = Query(..., description="Ticker symbol, e.g. AAPL"),
    range: str = Query("1M", description="One of 1D, 5D, 1W, 1M, 1Y"),
) -> dict:
    range_key = range.strip().upper()
    if range_key not in _VALID_RANGES:
        raise HTTPException(status_code=400, detail=f"range must be one of {sorted(_VALID_RANGES)}")
    provider = get_provider()
    try:
        points = provider.get_history(symbol.strip().upper(), range_key)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"symbol": symbol.strip().upper(), "range": range_key, "points": points}


@app.get("/api/public/news")
def public_news(symbols: str = Query("AAPL,MSFT,NVDA,TSLA,SPY", description="Comma-separated ticker symbols")) -> dict:
    provider = get_provider()
    try:
        items = provider.get_news(_parse_tickers(symbols))
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return {"items": items}


@app.get("/api/public/level2")
def public_level2(symbol: str = Query(..., description="Ticker symbol, e.g. AAPL")) -> dict:
    """A synthetic order book, clearly labeled as simulated.

    Real level 2 / market depth data requires a paid direct-exchange feed
    (e.g. Nasdaq TotalView, CBOE) that this app does not have access to --
    yfinance and other free sources do not provide it. Rather than pretend
    otherwise, this generates a plausible-looking book around the live quote
    for demo purposes, and every caller must surface `simulated: true`.
    """
    provider = get_provider()
    try:
        quote = provider.get_quote_detail(symbol.strip().upper())
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    price = quote["price"]
    tick = max(0.01, round(price * 0.0005, 2))
    rng = random.Random(f"{symbol.upper()}:{int(time.time() // 5)}")

    def ladder(direction: int) -> list[dict]:
        levels = []
        p = price
        for i in range(10):
            p = round(p + direction * tick * (1 + i * rng.uniform(0.8, 1.3)), 2)
            levels.append({"price": max(0.01, p), "size": rng.randint(1, 50) * 100})
        return levels

    return {
        "symbol": symbol.strip().upper(),
        "simulated": True,
        "disclaimer": (
            "Simulated data for demonstration only. Real Level 2 / market-depth "
            "data requires a paid exchange feed this app does not subscribe to."
        ),
        "bids": ladder(-1),
        "asks": ladder(1),
    }


# --- Trading (auth required) ---------------------------------------------------


@app.get("/api/broker/status")
def broker_status(username: str = Depends(require_auth)) -> dict:
    settings = get_settings()
    is_live = _is_live()
    return {
        "active_broker_setting": settings.active_broker,
        "live_trading_enabled": settings.live_trading_enabled,
        "effective_broker": "etrade" if is_live else "paper",
        "is_live": is_live,
    }


@app.get("/api/account")
def get_account(username: str = Depends(require_auth)) -> dict:
    try:
        return account_to_dict(get_broker().get_account())
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/positions")
def get_positions(username: str = Depends(require_auth)) -> dict:
    try:
        return {"positions": [position_to_dict(p) for p in get_broker().get_positions()]}
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/orders")
def list_orders(username: str = Depends(require_auth)) -> dict:
    try:
        return {"orders": [order_to_dict(o) for o in get_broker().list_orders()]}
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class OrderBody(BaseModel):
    symbol: str
    asset_type: str  # "equity" | "option"
    side: str  # "buy" | "sell"
    quantity: int
    order_type: str  # "market" | "limit"
    limit_price: Optional[float] = None
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[str] = None  # ISO date, e.g. "2026-09-25"
    rationale: Optional[str] = None
    confirm_live: bool = False


@app.post("/api/orders")
def place_order(body: OrderBody, username: str = Depends(require_auth)) -> dict:
    if _is_live() and not body.confirm_live:
        raise HTTPException(
            status_code=400,
            detail=(
                "LIVE TRADING is enabled and this would place a REAL order with real money. "
                "Resubmit with confirm_live=true to proceed."
            ),
        )
    try:
        expiration = date.fromisoformat(body.expiration) if body.expiration else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid expiration date: {exc}") from exc

    request = OrderRequest(
        symbol=body.symbol,
        asset_type=body.asset_type,
        side=body.side,
        quantity=body.quantity,
        order_type=body.order_type,
        limit_price=body.limit_price,
        option_type=body.option_type,
        strike=body.strike,
        expiration=expiration,
        rationale=body.rationale,
    )
    try:
        result = get_broker().place_order(request)
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return order_to_dict(result)


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int, username: str = Depends(require_auth)) -> dict:
    try:
        result = get_broker().cancel_order(order_id)
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return order_to_dict(result)


class EtradeCompleteAuthBody(BaseModel):
    request_token: str
    request_token_secret: str
    verifier: str


@app.get("/api/broker/etrade/auth-url")
def etrade_auth_url(username: str = Depends(require_auth)) -> dict:
    try:
        authorize_url, request_token, request_token_secret = ETradeBroker.start_authorization()
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "authorize_url": authorize_url,
        "request_token": request_token,
        "request_token_secret": request_token_secret,
    }


@app.post("/api/broker/etrade/complete-auth")
def etrade_complete_auth(body: EtradeCompleteAuthBody, username: str = Depends(require_auth)) -> dict:
    try:
        ETradeBroker.complete_authorization(body.request_token, body.request_token_secret, body.verifier)
    except BrokerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
