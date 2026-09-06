"""Core data models shared across providers, screener, and strategies."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass
class OptionContract:
    """A single option contract quote, as returned by a market data provider."""

    symbol: str  # underlying ticker, e.g. "AAPL"
    option_type: OptionType
    strike: float
    expiration: date
    bid: float
    ask: float
    last_price: float
    open_interest: int
    implied_volatility: float  # annualized, e.g. 0.35 for 35%
    contract_symbol: str = ""

    # Computed by greeks.enrich_contract() before screening.
    delta: Optional[float] = None
    days_to_expiration: Optional[int] = None

    @property
    def mid_price(self) -> float:
        if self.bid and self.ask:
            return round((self.bid + self.ask) / 2, 4)
        return self.last_price


@dataclass
class Underlying:
    symbol: str
    price: float
    dividend_yield: float = 0.0


@dataclass
class ScreeningCriteria:
    """Filters applied to every option contract before it can back a strategy idea.

    Defaults match the user's baseline screen: liquid contracts (OI > 100),
    meaningfully in-the-money-or-better exposure (|delta| >= 0.4), and enough
    runway to avoid extreme near-term gamma/theta risk (>= 2 weeks out).
    """

    min_open_interest: int = 100
    min_abs_delta: float = 0.4
    min_days_to_expiration: int = 14

    def passes(self, contract: OptionContract) -> bool:
        if contract.open_interest is None or contract.open_interest <= self.min_open_interest:
            return False
        if contract.delta is None:
            return False
        if abs(contract.delta) < self.min_abs_delta:
            return False
        if contract.days_to_expiration is None or contract.days_to_expiration < self.min_days_to_expiration:
            return False
        return True


@dataclass
class StrategyLeg:
    action: str  # "buy" or "sell"
    contract: Optional[OptionContract]  # None for the "buy 100 shares" leg
    quantity: int = 1
    description: str = ""


@dataclass
class StrategyIdea:
    strategy_key: str
    strategy_name: str
    trader_attribution: str
    symbol: str
    underlying_price: float
    legs: list[StrategyLeg]
    rationale: str
    max_profit: Optional[float]
    max_loss: Optional[float]
    breakeven: list[float]
    net_cost: float  # positive = debit paid, negative = credit received
