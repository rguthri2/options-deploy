"""Abstract broker interface. Mirrors the MarketDataProvider pattern in
app.providers so the paper simulator and real broker(s) are interchangeable
behind the same API routes."""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import AccountSummary, OrderRequest, OrderResult, Position


class BrokerError(RuntimeError):
    """Raised when a broker cannot complete a request (bad credentials,
    network error, rejected order, etc.)."""


class Broker(ABC):
    name: str

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        ...

    @abstractmethod
    def get_account(self) -> AccountSummary:
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        ...

    @abstractmethod
    def list_orders(self) -> list[OrderResult]:
        ...

    @abstractmethod
    def cancel_order(self, order_id: int) -> OrderResult:
        ...
