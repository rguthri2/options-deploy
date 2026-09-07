"""Broker-agnostic trading data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

ORDER_TYPES = ("market", "limit", "stop", "stop_limit", "trailing_stop")
TIME_IN_FORCE_VALUES = ("day", "gtc")


@dataclass
class OrderRequest:
    symbol: str
    asset_type: str  # "equity" | "option"
    side: str  # "buy" | "sell"
    quantity: int
    order_type: str  # see ORDER_TYPES
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None  # "stop" / "stop_limit" trigger level
    trail_amount: Optional[float] = None  # "trailing_stop": fixed $ trail
    trail_percent: Optional[float] = None  # "trailing_stop": % trail (exactly one of amount/percent)
    time_in_force: str = "day"  # "day" | "gtc"
    option_type: Optional[str] = None  # "call" | "put"
    strike: Optional[float] = None
    expiration: Optional[date] = None
    rationale: Optional[str] = None

    @property
    def contract_multiplier(self) -> int:
        return 100 if self.asset_type == "option" else 1

    def validate(self) -> Optional[str]:
        """Return an error message if invalid, else None."""
        if self.side not in ("buy", "sell"):
            return f"Invalid side '{self.side}'."
        if self.asset_type not in ("equity", "option"):
            return f"Invalid asset_type '{self.asset_type}'."
        if self.order_type not in ORDER_TYPES:
            return f"Invalid order_type '{self.order_type}'."
        if self.time_in_force not in TIME_IN_FORCE_VALUES:
            return f"Invalid time_in_force '{self.time_in_force}'."
        if self.quantity <= 0:
            return "Quantity must be positive."
        if self.order_type in ("limit", "stop_limit") and not self.limit_price:
            return "Limit and stop-limit orders require a limit_price."
        if self.order_type in ("stop", "stop_limit") and not self.stop_price:
            return "Stop and stop-limit orders require a stop_price."
        if self.order_type == "trailing_stop":
            if not self.trail_amount and not self.trail_percent:
                return "Trailing stop orders require a trail_amount or trail_percent."
            if self.trail_amount and self.trail_percent:
                return "Specify only one of trail_amount or trail_percent for a trailing stop."
        if self.asset_type == "option" and (not self.option_type or not self.strike or not self.expiration):
            return "Option orders require option_type, strike, and expiration."
        return None


@dataclass
class OrderResult:
    id: int
    broker: str
    symbol: str
    asset_type: str
    side: str
    quantity: int
    order_type: str
    status: str  # "pending" | "filled" | "canceled" | "rejected"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    trail_amount: Optional[float] = None
    trail_percent: Optional[float] = None
    trail_reference_price: Optional[float] = None
    time_in_force: str = "day"
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[str] = None
    filled_price: Optional[float] = None
    filled_at: Optional[str] = None
    broker_order_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    rationale: Optional[str] = None
    created_at: str = ""


@dataclass
class Position:
    symbol: str
    asset_type: str
    quantity: int  # positive = long, negative = short
    avg_cost: float  # per share/contract
    current_price: float
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiration: Optional[str] = None

    @property
    def contract_multiplier(self) -> int:
        return 100 if self.asset_type == "option" else 1

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price * self.contract_multiplier

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost * self.contract_multiplier

    @property
    def unrealized_pl(self) -> float:
        return self.market_value - self.cost_basis


@dataclass
class AccountSummary:
    broker: str
    cash_balance: float
    positions_value: float
    portfolio_value: float
    positions: list[Position] = field(default_factory=list)
