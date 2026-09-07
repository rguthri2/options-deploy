"""Abstract interface every market data provider implements.

Keeping this interface narrow (get underlying quote + get option chain) makes
it easy to swap the data source: yfinance for real usage, a deterministic mock
for local development, tests, and CI, or a broker/vendor API (e.g. Tradier,
Polygon, CBOE DataShop) later without touching the screener or strategies.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OptionContract, Underlying
from ..stock_screener import StockScreenCriteria


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

    def get_quote_detail(self, symbol: str) -> dict:
        """Return a richer quote for the public research page: price, prior
        close, day range, volume, market cap, company name. Optional --
        default raises so a provider that doesn't support it fails loudly
        rather than silently returning nonsense."""
        raise ProviderError(f"{type(self).__name__} does not support quote details.")

    def get_history(self, symbol: str, range_key: str) -> list[dict]:
        """Return [{"t": iso-timestamp, "c": close_price}, ...] for one of the
        range keys "1D", "5D", "1W", "1M", "1Y". Optional -- see get_quote_detail."""
        raise ProviderError(f"{type(self).__name__} does not support price history.")

    def get_news(self, symbols: list[str]) -> list[dict]:
        """Return recent news items: [{"title", "publisher", "link", "published_at"}, ...].
        Optional -- see get_quote_detail."""
        raise ProviderError(f"{type(self).__name__} does not support news.")

    def screen_stocks(self, criteria: StockScreenCriteria) -> list[dict]:
        """Return get_quote_detail()-shaped dicts matching `criteria`
        (price range, min volume, % change, min market cap), ranked by
        |% change| descending and capped at `criteria.limit`.
        Optional -- see get_quote_detail."""
        raise ProviderError(f"{type(self).__name__} does not support stock screening.")


class ProviderError(RuntimeError):
    """Raised when a provider cannot fetch data (bad symbol, network error, etc.)."""
