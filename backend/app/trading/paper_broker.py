"""Simulated broker: fills orders immediately against live quotes from the
configured MarketDataProvider, tracked in SQLite. No real money moves.

Deliberate MVP simplifications (documented rather than hidden):
  - Market orders fill immediately at the current quote. A *freshly placed*
    limit order fills immediately if marketable at the current quote,
    otherwise it is rejected outright -- this broker does not queue a
    resting limit order waiting for the market to move to it.
  - Stop, stop-limit, and trailing-stop orders DO rest, unlike plain limit
    orders above: they're stored "pending" and only fill once
    check_pending_orders() sees the market cross the trigger level. That
    sweep runs lazily (see app/main.py's account/positions/orders routes)
    and on a periodic background loop, so a trigger is caught whether or
    not anyone is actively looking at the page.
  - Selling more than you currently hold is rejected outright (no short
    selling in paper mode).
  - Realized P&L is not tracked separately; a position's average cost basis
    is a simple running weighted average across fills, unaffected by sells.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

from .. import db
from ..providers import MarketDataProvider, get_provider
from ..providers.base import ProviderError
from .base import Broker, BrokerError
from .models import AccountSummary, OrderRequest, OrderResult, Position
from .serializers import row_to_order_result

# NOTE: this is a plain assignment, not a type annotation -- `from __future__
# import annotations` only defers annotation evaluation, so `X | Y` syntax
# here would still execute immediately and crash on Python < 3.10. Use
# typing.Optional/Tuple instead of `|`/bare `tuple[...]` for exactly that
# reason (confirmed by an actual crash on a Python 3.9 deployment).
PositionKey = Tuple[str, str, Optional[str], Optional[float], Optional[str]]


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


def _request_from_row(row) -> OrderRequest:
    """Reconstruct just enough of an OrderRequest from a DB row to price and
    fill it -- used by check_pending_orders(), which only has the row."""
    return OrderRequest(
        symbol=row["symbol"],
        asset_type=row["asset_type"],
        side=row["side"],
        quantity=row["quantity"],
        order_type=row["order_type"],
        option_type=row["option_type"],
        strike=row["strike"],
        expiration=date.fromisoformat(row["expiration"]) if row["expiration"] else None,
    )


_row_to_result = row_to_order_result


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, provider: Optional[MarketDataProvider] = None):
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
            stop_price=request.stop_price,
            trail_amount=request.trail_amount,
            trail_percent=request.trail_percent,
            time_in_force=request.time_in_force,
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

        if request.order_type == "trailing_stop":
            # The trail needs a starting reference price to measure from;
            # check_pending_orders() takes it from here on every sweep. It
            # never fills at placement, even if -- by coincidence -- the
            # math would already call it triggered.
            db.update_order(order_id, trail_reference_price=current_price)
            self.check_pending_orders()
            return _row_to_result(db.get_order(order_id))

        if request.order_type in ("stop", "stop_limit"):
            # Rests until the market actually reaches the stop level.
            self.check_pending_orders()
            return _row_to_result(db.get_order(order_id))

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

        return self._execute_fill(order_id, request, fill_price)

    def _execute_fill(self, order_id: int, request: OrderRequest, fill_price: float) -> OrderResult:
        notional = fill_price * request.quantity * request.contract_multiplier

        if request.side == "buy":
            cash = db.get_paper_cash_balance()
            if notional > cash:
                db.update_order(
                    order_id,
                    status="rejected",
                    rejection_reason=f"Insufficient paper cash: need ${notional:,.2f}, have ${cash:,.2f}.",
                )
                return _row_to_result(db.get_order(order_id))
            db.set_paper_cash_balance(cash - notional)
        else:
            held = self._held_quantity(request)
            if request.quantity > held:
                db.update_order(
                    order_id,
                    status="rejected",
                    rejection_reason=f"Insufficient position to sell: hold {held}, tried to sell {request.quantity}.",
                )
                return _row_to_result(db.get_order(order_id))
            db.set_paper_cash_balance(db.get_paper_cash_balance() + notional)

        db.update_order(order_id, status="filled", filled_price=fill_price, filled_at=db.now_iso())
        return _row_to_result(db.get_order(order_id))

    def check_pending_orders(self) -> None:
        for row in db.list_pending_orders(self.name):
            order_type = row["order_type"]
            if order_type not in ("stop", "stop_limit", "trailing_stop"):
                continue  # a still-pending market/limit order was already resolved synchronously at placement

            request = _request_from_row(row)
            try:
                current_price = _current_price(self._provider, request)
            except BrokerError:
                continue  # can't price it right now; the next sweep will retry

            # For stop_limit, stop_price is cleared once the stop condition
            # fires -- that's this order's "already triggered, now just a
            # resting limit order at limit_price" marker, checked every
            # sweep from then on instead of re-testing the stop level.
            already_triggered = order_type == "stop_limit" and row["stop_price"] is None

            if not already_triggered:
                if order_type == "trailing_stop":
                    reference = row["trail_reference_price"]
                    if reference is None:
                        reference = current_price
                    reference = (
                        max(reference, current_price) if request.side == "sell" else min(reference, current_price)
                    )
                    if reference != row["trail_reference_price"]:
                        db.update_order(row["id"], trail_reference_price=reference)
                    trail = (
                        row["trail_amount"]
                        if row["trail_amount"] is not None
                        else reference * (row["trail_percent"] / 100.0)
                    )
                    effective_stop = reference - trail if request.side == "sell" else reference + trail
                else:
                    effective_stop = row["stop_price"]

                triggered = (
                    current_price <= effective_stop if request.side == "sell" else current_price >= effective_stop
                )
                if not triggered:
                    continue

                if order_type == "stop_limit":
                    db.update_order(row["id"], stop_price=None)

            if order_type == "stop_limit":
                limit_price = row["limit_price"]
                marketable = (request.side == "buy" and limit_price >= current_price) or (
                    request.side == "sell" and limit_price <= current_price
                )
                if not marketable:
                    continue  # triggered, now resting at limit_price -- re-check next sweep
                fill_price = limit_price
            else:
                fill_price = current_price

            self._execute_fill(row["id"], request, fill_price)

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
