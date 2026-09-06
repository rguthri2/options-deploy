"""Importing this package registers every built-in strategy."""
from .base import Strategy, all_strategies, get_strategy  # noqa: F401

from . import (  # noqa: F401,E402
    bear_put_spread,
    bull_call_spread,
    cash_secured_put,
    covered_call,
    long_call,
    long_put,
    poor_mans_covered_call,
    wheel,
)

__all__ = ["Strategy", "all_strategies", "get_strategy"]
