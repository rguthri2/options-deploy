from __future__ import annotations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, puts, register


class WheelStrategy(Strategy):
    key = "wheel"
    display_name = "The Wheel"
    trader_attribution = "Popularized across the retail options community (e.g. tastytrade, r/thetagang) as a repeatable income cycle"
    description = (
        "A repeating cycle: sell a cash-secured put; if assigned, sell covered "
        "calls against the resulting shares until they're called away, then "
        "restart. This scan surfaces the entry step -- the highest-conviction "
        "put to sell right now."
    )

    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        candidates = sorted(puts(screened_contracts), key=lambda c: abs(c.delta))
        ideas: list[StrategyIdea] = []
        seen_expirations: set = set()
        for put in candidates:
            if put.expiration in seen_expirations:
                continue
            seen_expirations.add(put.expiration)
            credit_per_share = put.mid_price
            put_leg = StrategyLeg(
                action="sell",
                contract=put,
                quantity=1,
                description="Step 1/3: Sell 1 cash-secured put",
            )
            cash_required = round(put.strike * 100, 2)
            max_profit = round(credit_per_share * 100, 2)
            max_loss = round(cash_required - credit_per_share * 100, 2)
            breakeven = round(put.strike - credit_per_share, 2)
            ideas.append(
                StrategyIdea(
                    strategy_key=self.key,
                    strategy_name=self.display_name,
                    trader_attribution=self.trader_attribution,
                    symbol=symbol,
                    underlying_price=underlying.price,
                    legs=[put_leg],
                    rationale=(
                        f"Wheel entry: sell the {put.expiration} ${put.strike:g} put (delta {put.delta:.2f}, "
                        f"OI {put.open_interest}) for ~${credit_per_share:.2f}/share. If assigned, sell calls "
                        f"against the {int(cash_required / put.strike)} shares at/above a ${put.strike:g} cost "
                        "basis (step 2/3), then repeat once called away (step 3/3)."
                    ),
                    max_profit=max_profit,
                    max_loss=max_loss,
                    breakeven=[breakeven],
                    net_cost=round(-credit_per_share * 100, 2),
                )
            )
            if len(ideas) >= self.max_ideas:
                break
        return ideas


register(WheelStrategy())
