"""Deterministic, offline sample data.

Used as the default provider so the app runs out of the box without network
access or API keys (handy for local development, demos, and CI/tests). Swap
to `DATA_PROVIDER=yfinance` for real market data.

The generated chains are intentionally varied -- open interest, strikes, and
expirations span both sides of the default screening thresholds -- so the
screener and strategy scans have something realistic to filter.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..models import OptionContract, OptionType, Underlying
from .base import MarketDataProvider, ProviderError

# symbol -> (spot price, dividend yield, base implied volatility)
_TICKER_PROFILES: dict[str, tuple[float, float, float]] = {
    "AAPL": (230.00, 0.005, 0.28),
    "MSFT": (420.00, 0.007, 0.25),
    "NVDA": (135.00, 0.0003, 0.55),
    "TSLA": (250.00, 0.0, 0.60),
    "SPY": (560.00, 0.013, 0.15),
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
