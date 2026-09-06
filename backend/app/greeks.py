"""Black-Scholes delta calculation.

We use Black-Scholes (rather than a full binomial/American-exercise model) as a
standard, dependency-free approximation for equity option delta. It is the
same approximation most retail screeners use for greeks derived from a
contract's implied volatility.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Optional

from .models import OptionContract, OptionType, Underlying

# Reasonable static assumption for the risk-free rate used in the Black-Scholes
# formula. This has a small effect on delta relative to implied volatility and
# time to expiration, so a static approximation is fine for screening purposes.
DEFAULT_RISK_FREE_RATE = 0.045


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_delta(
    *,
    spot: float,
    strike: float,
    years_to_expiration: float,
    volatility: float,
    option_type: OptionType,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
) -> Optional[float]:
    """Return the Black-Scholes delta for a European-style option.

    Returns None if inputs are degenerate (expired, no volatility, etc.) since
    delta is meaningless/undefined in those cases.
    """
    if spot <= 0 or strike <= 0 or years_to_expiration <= 0 or volatility <= 0:
        return None

    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility**2) * years_to_expiration
    ) / (volatility * math.sqrt(years_to_expiration))

    discount = math.exp(-dividend_yield * years_to_expiration)
    if option_type == OptionType.CALL:
        return discount * _norm_cdf(d1)
    return discount * (_norm_cdf(d1) - 1.0)


def days_to_expiration(expiration: date, as_of: Optional[date] = None) -> int:
    as_of = as_of or date.today()
    return (expiration - as_of).days


def enrich_contract(
    contract: OptionContract,
    underlying: Underlying,
    *,
    as_of: Optional[date] = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> OptionContract:
    """Fill in `delta` and `days_to_expiration` on a contract in place, and return it."""
    dte = days_to_expiration(contract.expiration, as_of=as_of)
    contract.days_to_expiration = dte

    years = dte / 365.0
    contract.delta = black_scholes_delta(
        spot=underlying.price,
        strike=contract.strike,
        years_to_expiration=years,
        volatility=contract.implied_volatility,
        option_type=contract.option_type,
        risk_free_rate=risk_free_rate,
        dividend_yield=underlying.dividend_yield,
    )
    return contract
