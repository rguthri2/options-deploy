import math

from app.providers.yfinance_provider import _extract_dividend_yield, _safe_float, _safe_int


def test_safe_float_handles_nan_and_none():
    assert _safe_float(float("nan"), default=1.5) == 1.5
    assert _safe_float(None, default=2.0) == 2.0
    assert _safe_float("12.5") == 12.5


def test_safe_int_handles_nan():
    # Real Yahoo Finance data returns NaN open interest for illiquid
    # contracts; int(NaN) raises ValueError, which this must avoid.
    assert _safe_int(float("nan")) == 0
    assert _safe_int(None) == 0
    assert _safe_int(150.0) == 150


def test_dividend_yield_prefers_unambiguous_fraction_field():
    info = {"trailingAnnualDividendYield": 0.0044, "dividendYield": 0.34}
    assert math.isclose(_extract_dividend_yield(info, 230.0), 0.0044)


def test_dividend_yield_falls_back_to_rate_over_price():
    info = {"trailingAnnualDividendRate": 1.04}
    assert math.isclose(_extract_dividend_yield(info, 230.0), 1.04 / 230.0)


def test_dividend_yield_last_resort_divides_ambiguous_field_by_100():
    # Observed live: yfinance returned dividendYield=0.34 for AAPL, meaning
    # 0.34%, not 34%.
    info = {"dividendYield": 0.34}
    assert math.isclose(_extract_dividend_yield(info, 230.0), 0.0034)


def test_dividend_yield_defaults_to_zero_when_missing():
    assert _extract_dividend_yield({}, 230.0) == 0.0
