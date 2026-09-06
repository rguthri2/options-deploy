"""Simulated broker: fills orders immediately against live quotes from the
configured MarketDataProvider, tracked in SQLite. No real money moves.

Deliberate MVP simplifications (documented rather than hidden):
  - Market orders fill immediately at the current quote. Limit orders fill
    immediately if marketable at the current quote, otherwise the order is
    rejected -- this broker does not queue resting limit orders waiting for
    the market to move to them.
  - Selling more than you currently hold is rejected outright (no short
    selling in paper mode).
  - Realized P&L is not tracked separately; a position's average cost basis
    is a simple running weighted average across fills, unaffected by sells.
"""
from __future__ import annotations

from datetime import date

from .. import db
from ..providers import MarketDataProvider, get_provider
from ..providers.base import ProviderError
from .base import Broker, BrokerError
from .models import AccountSummary, OrderRequest, OrderResult, Position
from .serializers import row_to_order_result

PositionKey = tuple[str, str, str | None, float | None, str | None]


def _current_price(provider: MarketDataProvider, request: OrderRequest) -> float:
    if request.asset_type == "equity":
        try:
            return provider.get_underlying(request.symbol).price
        except ProviderError as exc:
            raise BrokerError(str(exc)) from exc

    try:
        chain = provider.get_option_chain(request.symbol, min_days_to_expiration=0)
    except ProviderError as exc:
        raise BrokerError(str(exc)) from exc

    for contract in chain:
        if (
            contract.option_type.value == request.option_type
            and contract.strike == request.strike
            and contract.expiration == request.expiration
        ):
            return contract.mid_price
    raise BrokerError(
        f"No matching option contract found for {request.symbol} {request.expiration} "
        f"${request.strike} {request.option_type}."
    )


def _key_from_request(request: OrderRequest) -> PositionKey:
    return (
        request.symbol,
        request.asset_type,
        request.option_type,
        request.strike,
        request.expiration.isoformat() if request.expiration else None,
    )


def _key_from_row(row) -> PositionKey:
    return (row["symbol"], row["asset_type"], row["option_type"], row["strike"], row["expiration"])


_row_to_result = row_to_order_result


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, provider: MarketDataProvider | None = None):
        self._provider = provider or get_provider()

    def _held_quantity(self, request: OrderRequest) -> int:
        key = _key_from_request(request)
        held = 0
        for row in db.list_filled_orders(self.name):
            if _key_from_row(row) != key:
                continue
            held += row["quantity"] if row["side"] == "buy" else -row["quantity"]
        return held

    def place_order(self, request: OrderRequest) -> OrderResult:
        request.symbol = request.symbol.upper()
        error = request.validate()

        order_id = db.insert_order(
            broker=self.name,
            symbol=request.symbol,
            asset_type=request.asset_type,
            option_type=request.option_type,
            strike=request.strike,
            expiration=request.expiration.isoformat() if request.expiration else None,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            status="pending",
            rationale=request.rationale,
        )

        def reject(reason: str) -> OrderResult:
            db.update_order(order_id, status="rejected", rejection_reason=reason)
            return _row_to_result(db.get_order(order_id))

        if error:
            return reject(error)

        try:
            current_price = _current_price(self._provider, request)
        except BrokerError as exc:
            return reject(str(exc))

        if request.order_type == "limit":
            marketable = (request.side == "buy" and request.limit_price >= current_price) or (
                request.side == "sell" and request.limit_price <= current_price
            )
            if not marketable:
                return reject(
                    f"Limit price ${request.limit_price:.2f} is not marketable at the current "
                    f"quote (${current_price:.2f}); the paper broker fills immediately or rejects, "
                    "it does not queue resting limit orders."
                )
            fill_price = request.limit_price
        else:
            fill_price = current_price

        notional = fill_price * request.quantity * request.contract_multiplier

        if request.side == "buy":
            cash = db.get_paper_cash_balance()
            if notional > cash:
                return reject(f"Insufficient paper cash: need ${notional:,.2f}, have ${cash:,.2f}.")
            db.set_paper_cash_balance(cash - notional)
        else:
            held = self._held_quantity(request)
            if request.quantity > held:
                return reject(f"Insufficient position to sell: hold {held}, tried to sell {request.quantity}.")
            db.set_paper_cash_balance(db.get_paper_cash_balance() + notional)

        db.update_order(order_id, status="filled", filled_price=fill_price, filled_at=db.now_iso())
        return _row_to_result(db.get_order(order_id))

    def get_positions(self) -> list[Position]:
        book: dict[PositionKey, dict] = {}
        for row in db.list_filled_orders(self.name):
            key = _key_from_row(row)
            entry = book.setdefault(key, {"qty": 0, "avg_cost": 0.0})
            qty = row["quantity"]
            price = row["filled_price"]
            if row["side"] == "buy":
                total_cost = entry["avg_cost"] * entry["qty"] + price * qty
                entry["qty"] += qty
                entry["avg_cost"] = total_cost / entry["qty"] if entry["qty"] else 0.0
            else:
                entry["qty"] -= qty

        positions: list[Position] = []
        for (symbol, asset_type, option_type, strike, expiration), entry in book.items():
            if entry["qty"] == 0:
                continue
            probe = OrderRequest(
                symbol=symbol,
                asset_type=asset_type,
                side="buy",
                quantity=1,
                order_type="market",
                option_type=option_type,
                strike=strike,
                expiration=date.fromisoformat(expiration) if expiration else None,
            )
            try:
                current_price = _current_price(self._provider, probe)
            except BrokerError:
                current_price = entry["avg_cost"]
            positions.append(
                Position(
                    symbol=symbol,
                    asset_type=asset_type,
                    quantity=entry["qty"],
                    avg_cost=entry["avg_cost"],
                    current_price=current_price,
                    option_type=option_type,
                    strike=strike,
                    expiration=expiration,
                )
            )
        return positions

    def get_account(self) -> AccountSummary:
        cash = db.get_paper_cash_balance()
        positions = self.get_positions()
        positions_value = sum(p.market_value for p in positions)
        return AccountSummary(
            broker=self.name,
            cash_balance=cash,
            positions_value=positions_value,
            portfolio_value=cash + positions_value,
            positions=positions,
        )

    def list_orders(self) -> list[OrderResult]:
        return [_row_to_result(row) for row in db.list_orders(self.name)]

    def cancel_order(self, order_id: int) -> OrderResult:
        row = db.get_order(order_id)
        if row is None or row["broker"] != self.name:
            raise BrokerError(f"No paper order with id {order_id}.")
        if row["status"] != "pending":
            raise BrokerError(f"Order {order_id} is '{row['status']}' and cannot be canceled.")
        db.update_order(order_id, status="canceled")
        return _row_to_result(db.get_order(order_id))
