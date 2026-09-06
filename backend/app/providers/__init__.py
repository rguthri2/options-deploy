from __future__ import annotations

from ..config import get_settings
from .base import MarketDataProvider, ProviderError


def get_provider() -> MarketDataProvider:
    """Return the configured MarketDataProvider singleton-ish instance.

    Selection is controlled by the DATA_PROVIDER env var (see app.config):
      - "mock" (default): deterministic, offline sample data. Good for local
        development, demos, and CI where outbound network access to a market
        data vendor may not be available.
      - "yfinance": real market data pulled from Yahoo Finance via the
        `yfinance` package. Requires outbound network access and the
        `yfinance` dependency to be installed.
    """
    settings = get_settings()
    if settings.data_provider == "yfinance":
        from .yfinance_provider import YFinanceProvider

        return YFinanceProvider()
    from .mock_provider import MockProvider

    return MockProvider()


__all__ = ["MarketDataProvider", "ProviderError", "get_provider"]
