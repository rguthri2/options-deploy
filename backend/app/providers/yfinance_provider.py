"""Live market data via the `yfinance` package (scrapes Yahoo Finance).

Requires outbound network access to Yahoo Finance, which is not guaranteed in
every deployment environment (e.g. a sandboxed CI runner). Use MockProvider
for offline development/tests.
"""
from __future__ import annotations

import math
from datetime import date, datetime

from ..greeks import days_to_expiration
from ..models import OptionContract, OptionType, Underlying
from .base import MarketDataProvider, ProviderError


def _safe_float(value, default: float = 0.0) -> float:
    """Coerce a value (possibly None or NaN, as real Yahoo Finance data
    often is for illiquid contracts) to a plain float, falling back to
    `default` rather than propagating NaN or raising."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) else f


def _safe_int(value, default: int = 0) -> int:
    return int(_safe_float(value, default))


def _extract_dividend_yield(info: dict, price: float) -> float:
    """Return an annual dividend yield as a fraction (0.004 == 0.4%).

    `info["dividendYield"]` is notoriously ambiguous across yfinance/Yahoo
    API versions -- sometimes a fraction (0.004), sometimes a bare percentage
    number (0.4 meaning 0.4%) -- and the two conventions can't be told apart
    from magnitude alone when the true yield is small (0.34 could mean "34%"
    or "0.34%"). Prefer fields that are unambiguous: a fraction field, or a
    dollar dividend rate divided by price. Only fall back to the ambiguous
    field, with a magnitude-based guess, if nothing else is available.
    """
    trailing_fraction = info.get("trailingAnnualDividendYield")
    if trailing_fraction:
        v = _safe_float(trailing_fraction, -1)
        if 0 <= v < 0.5:
            return v

    rate = info.get("trailingAnnualDividendRate")
    if rate and price:
        v = _safe_float(rate) / price
        if 0 <= v < 0.5:
            return v

    # Last resort: `dividendYield` has flip-flopped between conventions
    # across yfinance/Yahoo API versions. Empirically (yfinance 1.2.0) it's a
    # bare percentage number -- e.g. 0.34 meaning 0.34%, not 34% -- so divide
    # by 100 unconditionally. If some other version ever puts a true fraction
    # here instead, this just underestimates a small yield rather than
    # wildly overestimating it (a 0.4% true yield would print rounded near 0
    # instead of jumping to 40%).
    raw = info.get("dividendYield")
    if raw:
        v = _safe_float(raw, -1) / 100.0
        if 0 <= v < 0.5:
            return v

    return 0.0


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
            dividend_yield = _extract_dividend_yield(info, price)
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
                            strike=_safe_float(getattr(row, "strike", 0.0)),
                            expiration=exp_date,
                            bid=_safe_float(getattr(row, "bid", 0.0)),
                            ask=_safe_float(getattr(row, "ask", 0.0)),
                            last_price=_safe_float(getattr(row, "lastPrice", 0.0)),
                            # Illiquid/no-interest contracts commonly come back
                            # with NaN here rather than 0.
                            open_interest=_safe_int(getattr(row, "openInterest", 0)),
                            implied_volatility=_safe_float(getattr(row, "impliedVolatility", 0.0)),
                            contract_symbol=str(getattr(row, "contractSymbol", "")),
                        )
                    )
        return contracts
