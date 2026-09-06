"""Strategy base class + registry.

Every strategy receives the *already-screened* option contracts for one
underlying (grouped by expiration) and produces zero or more StrategyIdea
concrete trade structures. Screening (open interest, delta, expiration) has
already been applied upstream by `app.screener`, so strategies only need to
combine legs and compute payoff numbers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict

from ..models import OptionContract, OptionType, StrategyIdea, Underlying


def group_by_expiration(contracts: list[OptionContract]) -> dict:
    grouped: dict = defaultdict(list)
    for c in contracts:
        grouped[c.expiration].append(c)
    return dict(sorted(grouped.items()))


def calls(contracts: list[OptionContract]) -> list[OptionContract]:
    return [c for c in contracts if c.option_type == OptionType.CALL]


def puts(contracts: list[OptionContract]) -> list[OptionContract]:
    return [c for c in contracts if c.option_type == OptionType.PUT]


class Strategy(ABC):
    key: str
    display_name: str
    trader_attribution: str
    description: str
    # Max number of ideas a single scan() call should return, so the API
    # doesn't dump every combinatorial pairing for a busy option chain.
    max_ideas: int = 3

    @abstractmethod
    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        """Return candidate trade ideas built only from `screened_contracts`."""

    def metadata(self) -> dict:
        return {
            "key": self.key,
            "name": self.display_name,
            "trader_attribution": self.trader_attribution,
            "description": self.description,
        }


_REGISTRY: dict[str, Strategy] = {}


def register(strategy: Strategy) -> Strategy:
    _REGISTRY[strategy.key] = strategy
    return strategy


def all_strategies() -> list[Strategy]:
    return list(_REGISTRY.values())


def get_strategy(key: str) -> Strategy | None:
    return _REGISTRY.get(key)
