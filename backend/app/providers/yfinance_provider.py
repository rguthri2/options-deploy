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

    def get_quote_detail(self, symbol: str) -> dict:
        ticker = self._yf.Ticker(symbol)
        try:
            fast_info = ticker.fast_info
            price = _safe_float(fast_info["lastPrice"])
            previous_close = _safe_float(fast_info.get("previousClose"), price)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Could not fetch a quote for '{symbol}': {exc}") from exc

        name = symbol.upper()
        market_cap = None
        try:
            info = ticker.info
            name = info.get("shortName") or info.get("longName") or name
            market_cap = info.get("marketCap")
        except Exception:  # noqa: BLE001 - name/market cap are nice-to-haves
            pass

        change = price - previous_close
        change_percent = (change / previous_close * 100.0) if previous_close else 0.0
        return {
            "symbol": symbol.upper(),
            "name": name,
            "price": round(price, 2),
            "previous_close": round(previous_close, 2),
            "change": round(change, 2),
            "change_percent": round(change_percent, 2),
            "day_high": round(_safe_float(fast_info.get("dayHigh"), price), 2),
            "day_low": round(_safe_float(fast_info.get("dayLow"), price), 2),
            "volume": _safe_int(fast_info.get("lastVolume")),
            "market_cap": market_cap,
        }

    def get_history(self, symbol: str, range_key: str) -> list[dict]:
        period, interval = {
            "1D": ("1d", "5m"),
            "5D": ("5d", "30m"),
            "1W": ("5d", "1h"),
            "1M": ("1mo", "1d"),
            "1Y": ("1y", "1wk"),
        }.get(range_key, ("1mo", "1d"))
        ticker = self._yf.Ticker(symbol)
        try:
            hist = ticker.history(period=period, interval=interval)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Could not fetch price history for '{symbol}': {exc}") from exc
        points = []
        for ts, row in hist.iterrows():
            close = _safe_float(row.get("Close"), None)
            if close is None:
                continue
            points.append({"t": ts.isoformat(), "c": round(close, 2)})
        return points

    def get_news(self, symbols: list[str]) -> list[dict]:
        items: list[dict] = []
        for symbol in symbols:
            try:
                raw_items = self._yf.Ticker(symbol).news or []
            except Exception:  # noqa: BLE001 - news is best-effort
                continue
            for raw in raw_items[:8]:
                content = raw.get("content", raw)  # newer yfinance nests fields under "content"
                title = content.get("title")
                if not title:
                    continue
                link = (content.get("canonicalUrl") or {}).get("url") or content.get("link") or ""
                publisher = (content.get("provider") or {}).get("displayName") or content.get("publisher") or ""
                published_at = content.get("pubDate") or content.get("providerPublishTime") or ""
                items.append(
                    {
                        "symbol": symbol.upper(),
                        "title": title,
                        "publisher": publisher,
                        "link": link,
                        "published_at": str(published_at),
                    }
                )
        return items
