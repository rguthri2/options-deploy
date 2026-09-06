"""Broker-agnostic trading data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class OrderRequest:
    symbol: str
    asset_type: str  # "equity" | "option"
    side: str  # "buy" | "sell"
    quantity: int
    order_type: str  # "market" | "limit"
    limit_price: Optional[float] = None
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
        if self.order_type not in ("market", "limit"):
            return f"Invalid order_type '{self.order_type}'."
        if self.quantity <= 0:
            return "Quantity must be positive."
        if self.order_type == "limit" and not self.limit_price:
            return "Limit orders require a limit_price."
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
