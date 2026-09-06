"""Abstract interface every market data provider implements.

Keeping this interface narrow (get underlying quote + get option chain) makes
it easy to swap the data source: yfinance for real usage, a deterministic mock
for local development, tests, and CI, or a broker/vendor API (e.g. Tradier,
Polygon, CBOE DataShop) later without touching the screener or strategies.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OptionContract, Underlying


class MarketDataProvider(ABC):
    @abstractmethod
    def get_underlying(self, symbol: str) -> Underlying:
        """Return the current quote for a stock symbol."""

    @abstractmethod
    def get_option_chain(self, symbol: str, *, min_days_to_expiration: int = 0) -> list[OptionContract]:
        """Return all listed option contracts for a symbol.

        Implementations may use `min_days_to_expiration` to skip fetching
        expirations that could never pass screening, but are not required to
        filter precisely -- the screener re-checks everything.
        """


class ProviderError(RuntimeError):
    """Raised when a provider cannot fetch data (bad symbol, network error, etc.)."""
