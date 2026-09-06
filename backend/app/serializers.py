"""Plain-dict serializers for our dataclasses (kept separate from pydantic
request/response models since the domain models are simple frozen dataclasses)."""
from __future__ import annotations

from .models import OptionContract, StrategyIdea, Underlying


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
