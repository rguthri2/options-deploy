"""Criteria-based stock screening: filters and ranks quote-level data
(price, volume, % change, market cap) independent of any specific market
data provider. Providers translate `StockScreenCriteria` into whatever
their own data source needs (a live vendor-side query, or -- for the
offline mock provider -- a plain filter over its fixed quote list via
`filter_and_rank`); see `MarketDataProvider.screen_stocks()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StockScreenCriteria:
    min_price: float = 0.0
    max_price: Optional[float] = None
    min_volume: int = 0
    min_change_pct: float = 0.0  # magnitude threshold; sign is picked by `direction`
    direction: str = "either"  # "gainers" | "losers" | "either"
    min_market_cap: float = 0.0
    limit: int = 25


def passes(quote: dict, criteria: StockScreenCriteria) -> bool:
    """Whether one get_quote_detail()-shaped dict clears every filter."""
    price = quote.get("price")
    if price is None or price < criteria.min_price:
        return False
    if criteria.max_price is not None and price > criteria.max_price:
        return False

    volume = quote.get("volume") or 0
    if volume < criteria.min_volume:
        return False

    if criteria.min_market_cap > 0:
        market_cap = quote.get("market_cap")
        if market_cap is None or market_cap < criteria.min_market_cap:
            return False

    change_pct = quote.get("change_percent") or 0.0
    if criteria.direction == "gainers":
        if change_pct < criteria.min_change_pct:
            return False
    elif criteria.direction == "losers":
        if change_pct > -criteria.min_change_pct:
            return False
    else:
        if abs(change_pct) < criteria.min_change_pct:
            return False

    return True


def filter_and_rank(quotes: list[dict], criteria: StockScreenCriteria) -> list[dict]:
    """Apply `passes` to every quote, then rank movers first (largest
    |% change|) and cap at `criteria.limit`."""
    matched = [q for q in quotes if passes(q, criteria)]
    matched.sort(key=lambda q: abs(q.get("change_percent") or 0.0), reverse=True)
    return matched[: criteria.limit]
