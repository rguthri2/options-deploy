"""Field registry + dynamic min/max filtering for the RG Profit Options
Screener's "Add Scan Filters" picker (`/api/public/scan-fields`,
`/api/public/profit-screener?filters=...`).

Deliberately a curated SUBSET of what Think-or-Swim's own "Add Scan
Filters" dialog offers, not a full replica -- about half of ToS's fields
(Bid/Ask/Bid Size/Ask Size/Last Size/Mark, and every volatility-surface or
options-tape field: Back/Front/Weighted Back Volatility, Volatility
Index/Difference, Market Maker Move, Call/Put Volume Index, Put/Call Ratio)
come from a live Level 1/2 quote feed or an aggregated options tape that no
free data source (yfinance included) exposes. Rather than fake those with
guessed numbers, this registry only lists fields this app's providers can
actually compute -- real stock quote/volume data plus the subset of
fundamentals yfinance's `ticker.info` reliably carries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScanField:
    key: str  # matches a key in the enriched quote dict
    label: str
    category: str  # "Price & Volume" | "Fundamentals"
    unit: str = ""  # "$" | "%" | "x" | ""


SCAN_FIELDS: list[ScanField] = [
    ScanField("price", "Last", "Price & Volume", "$"),
    ScanField("open", "Open", "Price & Volume", "$"),
    ScanField("day_high", "High", "Price & Volume", "$"),
    ScanField("day_low", "Low", "Price & Volume", "$"),
    ScanField("previous_close", "Close", "Price & Volume", "$"),
    ScanField("change", "Net Change", "Price & Volume", "$"),
    ScanField("change_percent", "Percent Change", "Price & Volume", "%"),
    ScanField("volume", "Volume", "Price & Volume", ""),
    ScanField("avg_volume", "Average Volume", "Price & Volume", ""),
    ScanField("relative_volume", "Relative Volume", "Price & Volume", "x"),
    ScanField("atr", "ATR", "Price & Volume", "$"),
    ScanField("year_high", "52-Week High", "Price & Volume", "$"),
    ScanField("year_low", "52-Week Low", "Price & Volume", "$"),
    ScanField("beta", "Beta", "Price & Volume", ""),
    ScanField("market_cap", "Market Cap", "Fundamentals", "$"),
    ScanField("pe_ratio", "P/E Ratio", "Fundamentals", ""),
    ScanField("eps", "EPS", "Fundamentals", "$"),
    ScanField("dividend_yield_pct", "Dividend Yield", "Fundamentals", "%"),
    ScanField("price_to_book", "Price/Book Value Ratio", "Fundamentals", ""),
    ScanField("return_on_equity_pct", "Return on Equity (ROE)", "Fundamentals", "%"),
    ScanField("profit_margin_pct", "Net Profit Margin", "Fundamentals", "%"),
]

SCAN_FIELDS_BY_KEY: dict[str, ScanField] = {f.key: f for f in SCAN_FIELDS}


@dataclass(frozen=True)
class ScanFilter:
    field: str
    min: Optional[float] = None
    max: Optional[float] = None


def apply_filters(rows: list[dict], filters: list[ScanFilter]) -> list[dict]:
    """Keep only rows where every filter's field is present and within
    [min, max] (either bound optional). A row missing a filtered field
    entirely (e.g. a fundamental yfinance couldn't fetch) is excluded --
    silently passing it would misrepresent an unknown value as a match."""
    if not filters:
        return rows
    out = []
    for row in rows:
        ok = True
        for f in filters:
            value = row.get(f.field)
            if value is None:
                ok = False
                break
            if f.min is not None and value < f.min:
                ok = False
                break
            if f.max is not None and value > f.max:
                ok = False
                break
        if ok:
            out.append(row)
    return out
