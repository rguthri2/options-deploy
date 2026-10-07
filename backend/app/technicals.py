"""Server-side technical math that reduces a run of OHLCV bars (see
`MarketDataProvider.get_history()`) to a single number per symbol -- used by
the profit screener's Average True Range and average-volume columns. This is
deliberately separate from the client-side indicator math in
frontend/site.js (SMA/EMA/Bollinger/RSI/MACD), which plots a series on a
chart rather than producing one scalar per symbol.
"""
from __future__ import annotations

from typing import Optional


def average_true_range(bars: list[dict], period: int = 14) -> Optional[float]:
    """Wilder's ATR over the most recent `period` daily bars.

    Needs `period + 1` bars (one extra so the first true-range value has a
    prior close to compare against); returns None rather than a misleading
    number computed from too little history.
    """
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(bars)):
        high, low, prev_close = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return round(sum(true_ranges[-period:]) / period, 4)


def average_volume(bars: list[dict], period: int = 20) -> Optional[float]:
    """Mean volume over the most recent `period` bars, or fewer if that's
    all there is -- unlike ATR, a rough average from partial history is
    still a usable baseline for relative volume, so this has no minimum."""
    if not bars:
        return None
    recent = bars[-period:]
    return round(sum(b["v"] for b in recent) / len(recent), 0)
