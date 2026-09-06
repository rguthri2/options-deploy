"""Plain-dict serializers for our dataclasses (kept separate from pydantic
request/response models since the domain models are simple frozen dataclasses)."""
from __future__ import annotations

from .models import OptionContract, StrategyIdea, Underlying
from .trading.models import AccountSummary, OrderResult, Position


def contract_to_dict(c: OptionContract) -> dict:
    return {
        "symbol": c.symbol,
        "option_type": c.option_type.value,
        "strike": c.strike,
        "expiration": c.expiration.isoformat(),
        "days_to_expiration": c.days_to_expiration,
        "bid": c.bid,
        "ask": c.ask,
        "mid_price": c.mid_price,
        "last_price": c.last_price,
        "open_interest": c.open_interest,
        "implied_volatility": c.implied_volatility,
        "delta": round(c.delta, 4) if c.delta is not None else None,
        "contract_symbol": c.contract_symbol,
    }


def underlying_to_dict(u: Underlying) -> dict:
    return {"symbol": u.symbol, "price": u.price, "dividend_yield": u.dividend_yield}


def idea_to_dict(idea: StrategyIdea) -> dict:
    return {
        "strategy_key": idea.strategy_key,
        "strategy_name": idea.strategy_name,
        "trader_attribution": idea.trader_attribution,
        "symbol": idea.symbol,
        "underlying_price": idea.underlying_price,
        "legs": [
            {
                "action": leg.action,
                "quantity": leg.quantity,
                "description": leg.description,
                "contract": contract_to_dict(leg.contract) if leg.contract else None,
            }
            for leg in idea.legs
        ],
        "rationale": idea.rationale,
        "max_profit": idea.max_profit,
        "max_loss": idea.max_loss,
        "breakeven": idea.breakeven,
        "net_cost": idea.net_cost,
    }


def order_to_dict(o: OrderResult) -> dict:
    return {
        "id": o.id,
        "broker": o.broker,
        "symbol": o.symbol,
        "asset_type": o.asset_type,
        "side": o.side,
        "quantity": o.quantity,
        "order_type": o.order_type,
        "status": o.status,
        "limit_price": o.limit_price,
        "option_type": o.option_type,
        "strike": o.strike,
        "expiration": o.expiration,
        "filled_price": o.filled_price,
        "filled_at": o.filled_at,
        "broker_order_id": o.broker_order_id,
        "rejection_reason": o.rejection_reason,
        "rationale": o.rationale,
        "created_at": o.created_at,
    }


def position_to_dict(p: Position) -> dict:
    return {
        "symbol": p.symbol,
        "asset_type": p.asset_type,
        "quantity": p.quantity,
        "avg_cost": p.avg_cost,
        "current_price": p.current_price,
        "option_type": p.option_type,
        "strike": p.strike,
        "expiration": p.expiration,
        "market_value": round(p.market_value, 2),
        "cost_basis": round(p.cost_basis, 2),
        "unrealized_pl": round(p.unrealized_pl, 2),
    }


def account_to_dict(a: AccountSummary) -> dict:
    return {
        "broker": a.broker,
        "cash_balance": round(a.cash_balance, 2),
        "positions_value": round(a.positions_value, 2),
        "portfolio_value": round(a.portfolio_value, 2),
        "positions": [position_to_dict(p) for p in a.positions],
    }
