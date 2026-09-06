from __future__ import annotations

from .models import OrderResult


def row_to_order_result(row) -> OrderResult:
    return OrderResult(
        id=row["id"],
        broker=row["broker"],
        symbol=row["symbol"],
        asset_type=row["asset_type"],
        side=row["side"],
        quantity=row["quantity"],
        order_type=row["order_type"],
        status=row["status"],
        limit_price=row["limit_price"],
        option_type=row["option_type"],
        strike=row["strike"],
        expiration=row["expiration"],
        filled_price=row["filled_price"],
        filled_at=row["filled_at"],
        broker_order_id=row["broker_order_id"],
        rejection_reason=row["rejection_reason"],
        rationale=row["rationale"],
        created_at=row["created_at"],
    )
