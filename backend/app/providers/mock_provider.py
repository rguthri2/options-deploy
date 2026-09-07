"""Deterministic, offline sample data.

Used as the default provider so the app runs out of the box without network
access or API keys (handy for local development, demos, and CI/tests). Swap
to `DATA_PROVIDER=yfinance` for real market data.

The generated chains are intentionally varied -- open interest, strikes, and
expirations span both sides of the default screening thresholds -- so the
screener and strategy scans have something realistic to filter.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from ..models import OptionContract, OptionType, Underlying
from ..stock_screener import StockScreenCriteria, filter_and_rank
from .base import MarketDataProvider, ProviderError

_COMPANY_NAMES: dict[str, str] = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "NVDA": "NVIDIA Corporation",
    "TSLA": "Tesla, Inc.",
    "SPY": "SPDR S&P 500 ETF Trust",
    "GOOGL": "Alphabet Inc.",
    "AMZN": "Amazon.com, Inc.",
    "META": "Meta Platforms, Inc.",
    "AMD": "Advanced Micro Devices, Inc.",
    "NFLX": "Netflix, Inc.",
    "JPM": "JPMorgan Chase & Co.",
}

_RANGE_POINTS: dict[str, int] = {"1D": 26, "5D": 30, "1W": 30, "1M": 22, "1Y": 52}

# symbol -> (spot price, dividend yield, base implied volatility)
_TICKER_PROFILES: dict[str, tuple[float, float, float]] = {
    "AAPL": (230.00, 0.005, 0.28),
    "MSFT": (420.00, 0.007, 0.25),
    "NVDA": (135.00, 0.0003, 0.55),
    "TSLA": (250.00, 0.0, 0.60),
    "SPY": (560.00, 0.013, 0.15),
    "GOOGL": (175.00, 0.005, 0.30),
    "AMZN": (185.00, 0.0, 0.32),
    "META": (580.00, 0.003, 0.35),
    "AMD": (145.00, 0.0, 0.45),
    "NFLX": (700.00, 0.0, 0.35),
    "JPM": (215.00, 0.021, 0.22),
}

# symbol -> approximate market cap in dollars, for testing `min_market_cap`
# filtering offline. SPY is an ETF (no market cap) -- left out on purpose so
# screening exercises the "unknown market cap" exclusion path too.
_MARKET_CAPS: dict[str, float] = {
    "AAPL": 3.4e12,
    "MSFT": 3.1e12,
    "NVDA": 3.3e12,
    "TSLA": 0.8e12,
    "GOOGL": 2.2e12,
    "AMZN": 2.0e12,
    "META": 1.4e12,
    "AMD": 0.25e12,
    "NFLX": 0.3e12,
    "JPM": 0.65e12,
}

# Days-to-expiration cycles offered per symbol. One is deliberately < 14 days
# so the "expiration >= 2 weeks" filter has something to reject.
_DTE_CYCLES = [7, 21, 45, 90, 365]

# Strike offsets (as a fraction of spot) around at-the-money, wide enough to
# produce contracts on both sides of the |delta| >= 0.4 line.
_STRIKE_OFFSETS = [-0.20, -0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.20]


def _round_strike(value: float) -> float:
    if value >= 200:
        step = 5.0
    elif value >= 50:
        step = 2.5
    else:
        step = 1.0
    return round(value / step) * step


def _open_interest_for(offset: float, dte: int) -> int:
    """More open interest near-the-money and in nearer-dated contracts;
    deliberately dips below the 100 threshold far out-of-the-money."""
    base = 1200 if dte <= 45 else 400
    decay = max(0.02, 1.0 - abs(offset) * 4.0)
    return max(20, int(base * decay))


def _iv_for(base_iv: float, offset: float, dte: int) -> float:
    # Mild volatility smile (wings trade at higher IV) and mild term structure.
    smile = 1.0 + abs(offset) * 1.5
    term = 1.0 + (0.05 if dte >= 180 else 0.0)
    return round(base_iv * smile * term, 4)


def _spread_for(mid: float) -> tuple[float, float]:
    half_spread = max(0.02, round(mid * 0.03, 2))
    return round(max(0.0, mid - half_spread), 2), round(mid + half_spread, 2)


def build_mock_chain(symbol: str, spot: float, dividend_yield: float, base_iv: float) -> list[OptionContract]:
    today = date.today()
    contracts: list[OptionContract] = []
    for dte in _DTE_CYCLES:
        expiration = today + timedelta(days=dte)
        for offset in _STRIKE_OFFSETS:
            strike = _round_strike(spot * (1 + offset))
            for option_type in (OptionType.CALL, OptionType.PUT):
                intrinsic = max(0.0, (spot - strike) if option_type == OptionType.CALL else (strike - spot))
                time_value = max(0.05, spot * 0.02 * (dte / 30.0) ** 0.5 * base_iv / 0.3)
                mid = round(intrinsic + time_value, 2)
                bid, ask = _spread_for(mid)
                contracts.append(
                    OptionContract(
                        symbol=symbol,
                        option_type=option_type,
                        strike=strike,
                        expiration=expiration,
                        bid=bid,
                        ask=ask,
                        last_price=mid,
                        open_interest=_open_interest_for(offset, dte),
                        implied_volatility=_iv_for(base_iv, offset, dte),
                        contract_symbol=f"{symbol}{expiration:%y%m%d}{'C' if option_type == OptionType.CALL else 'P'}{int(strike * 1000):08d}",
                    )
                )
    return contracts


class MockProvider(MarketDataProvider):
    def get_underlying(self, symbol: str) -> Underlying:
        profile = _TICKER_PROFILES.get(symbol.upper())
        if not profile:
            raise ProviderError(
                f"Unknown mock symbol '{symbol}'. Available in mock mode: "
                f"{', '.join(sorted(_TICKER_PROFILES))}. Set DATA_PROVIDER=yfinance for any live symbol."
            )
        price, dividend_yield, _ = profile
        return Underlying(symbol=symbol.upper(), price=price, dividend_yield=dividend_yield)

    def get_option_chain(self, symbol: str, *, min_days_to_expiration: int = 0) -> list[OptionContract]:
        profile = _TICKER_PROFILES.get(symbol.upper())
        if not profile:
            raise ProviderError(
                f"Unknown mock symbol '{symbol}'. Available in mock mode: "
                f"{', '.join(sorted(_TICKER_PROFILES))}. Set DATA_PROVIDER=yfinance for any live symbol."
            )
        price, dividend_yield, base_iv = profile
        chain = build_mock_chain(symbol.upper(), price, dividend_yield, base_iv)
        if min_days_to_expiration:
            today = date.today()
            chain = [c for c in chain if (c.expiration - today).days >= min_days_to_expiration]
        return chain

    def get_quote_detail(self, symbol: str) -> dict:
        underlying = self.get_underlying(symbol)
        rng = random.Random(symbol.upper())
        previous_close = round(underlying.price * (1 + rng.uniform(-0.02, 0.02)), 2)
        change = round(underlying.price - previous_close, 2)
        change_percent = round((change / previous_close * 100.0) if previous_close else 0.0, 2)
        return {
            "symbol": underlying.symbol,
            "name": _COMPANY_NAMES.get(underlying.symbol, underlying.symbol),
            "price": underlying.price,
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
            "day_high": round(underlying.price * 1.01, 2),
            "day_low": round(underlying.price * 0.99, 2),
            "volume": rng.randint(2_000_000, 60_000_000),
            "market_cap": _MARKET_CAPS.get(underlying.symbol),
        }

    def screen_stocks(self, criteria: StockScreenCriteria) -> list[dict]:
        quotes = [self.get_quote_detail(symbol) for symbol in sorted(_TICKER_PROFILES)]
        return filter_and_rank(quotes, criteria)

    def get_history(self, symbol: str, range_key: str) -> list[dict]:
        underlying = self.get_underlying(symbol)
        n_points = _RANGE_POINTS.get(range_key, 22)
        rng = random.Random(f"{symbol.upper()}:{range_key}")
        price = underlying.price * rng.uniform(0.92, 1.0)
        now = datetime.now(timezone.utc)
        step = {
            "1D": timedelta(minutes=15),
            "5D": timedelta(hours=2),
            "1W": timedelta(hours=6),
            "1M": timedelta(days=1),
            "1Y": timedelta(weeks=1),
        }.get(range_key, timedelta(days=1))

        points = []
        for i in range(n_points):
            price *= 1 + rng.uniform(-0.015, 0.016)
            ts = now - step * (n_points - 1 - i)
            points.append({"t": ts.isoformat(), "c": round(price, 2)})
        # Nudge the last point to land on the "current" quote so the chart
        # ends where the rest of the UI says the price is.
        if points:
            points[-1]["c"] = underlying.price
        return points

    def get_news(self, symbols: list[str]) -> list[dict]:
        headlines = [
            "shares active in early trading as options volume picks up",
            "analysts weigh in ahead of next earnings report",
            "options market pricing in elevated volatility",
            "trading desks watch key technical level closely",
            "volume surges on heavier-than-usual options activity",
        ]
        now = datetime.now(timezone.utc)
        items = []
        for i, symbol in enumerate(symbols):
            rng = random.Random(f"news:{symbol.upper()}")
            name = _COMPANY_NAMES.get(symbol.upper(), symbol.upper())
            items.append(
                {
                    "symbol": symbol.upper(),
                    "title": f"{name} ({symbol.upper()}) {rng.choice(headlines)}",
                    "publisher": "Sample Market Wire (demo data)",
                    "link": "",
                    "published_at": (now - timedelta(hours=i * 3 + 1)).isoformat(),
                }
            )
        return items
