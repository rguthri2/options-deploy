"""Filters a raw option chain down to contracts that pass the screening criteria."""
from __future__ import annotations

from datetime import date
from typing import Optional

from .greeks import enrich_contract
from .models import OptionContract, ScreeningCriteria, Underlying


def screen_chain(
    contracts: list[OptionContract],
    underlying: Underlying,
    criteria: Optional[ScreeningCriteria] = None,
    *,
    as_of: Optional[date] = None,
) -> list[OptionContract]:
    """Enrich each contract with delta/DTE, then return only the ones passing `criteria`."""
    criteria = criteria or ScreeningCriteria()
    enriched = [enrich_contract(c, underlying, as_of=as_of) for c in contracts]
    return [c for c in enriched if criteria.passes(c)]
