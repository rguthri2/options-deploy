"""Live market data via the `yfinance` package (scrapes Yahoo Finance).

Requires outbound network access to Yahoo Finance, which is not guaranteed in
every deployment environment (e.g. a sandboxed CI runner). Use MockProvider
for offline development/tests.
"""
from __future__ import annotations

from datetime import date, datetime

from ..greeks import days_to_expiration
from ..models import OptionContract, OptionType, Underlying
from .base import MarketDataProvider, ProviderError


class YFinanceProvider(MarketDataProvider):
    def __init__(self) -> None:
        try:
            import yfinance as yf  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only without the dep installed
            raise ProviderError(
                "yfinance is not installed. Run `pip install yfinance` or set "
                "DATA_PROVIDER=mock to use sample data instead."
            ) from exc
        self._yf = yf

    def get_underlying(self, symbol: str) -> Underlying:
        ticker = self._yf.Ticker(symbol)
        try:
            fast_info = ticker.fast_info
            price = float(fast_info["lastPrice"])
        except Exception as exc:  # noqa: BLE001 - vendor lib raises varied exceptions
            raise ProviderError(f"Could not fetch a quote for '{symbol}': {exc}") from exc

        dividend_yield = 0.0
        try:
            info = ticker.info
            dividend_yield = float(info.get("dividendYield") or 0.0)
            # yfinance sometimes returns a percentage (e.g. 0.5 for 0.5%)
            # and sometimes a fraction (e.g. 0.005) depending on version;
            # normalize anything implausibly large for a yield.
            if dividend_yield > 1:
                dividend_yield /= 100.0
        except Exception:  # noqa: BLE001 - dividend yield is a nice-to-have
            dividend_yield = 0.0

        return Underlying(symbol=symbol.upper(), price=price, dividend_yield=dividend_yield)

    def get_option_chain(self, symbol: str, *, min_days_to_expiration: int = 0) -> list[OptionContract]:
        ticker = self._yf.Ticker(symbol)
        try:
            expirations = ticker.options
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Could not fetch option expirations for '{symbol}': {exc}") from exc

        contracts: list[OptionContract] = []
        today = date.today()
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            if days_to_expiration(exp_date, as_of=today) < min_days_to_expiration:
                continue
            try:
                chain = ticker.option_chain(exp_str)
            except Exception:  # noqa: BLE001 - skip expirations Yahoo fails to serve
                continue

            for option_type, frame in ((OptionType.CALL, chain.calls), (OptionType.PUT, chain.puts)):
                for row in frame.itertuples():
                    contracts.append(
                        OptionContract(
                            symbol=symbol.upper(),
                            option_type=option_type,
                            strike=float(row.strike),
                            expiration=exp_date,
                            bid=float(getattr(row, "bid", 0.0) or 0.0),
                            ask=float(getattr(row, "ask", 0.0) or 0.0),
                            last_price=float(getattr(row, "lastPrice", 0.0) or 0.0),
                            open_interest=int(getattr(row, "openInterest", 0) or 0),
                            implied_volatility=float(getattr(row, "impliedVolatility", 0.0) or 0.0),
                            contract_symbol=str(getattr(row, "contractSymbol", "")),
                        )
                    )
        return contracts
