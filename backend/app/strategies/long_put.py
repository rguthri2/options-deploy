from __future__ import annotations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, puts, register


class LongPutStrategy(Strategy):
    key = "long_put"
    display_name = "Long Put (Directional / Hedge)"
    trader_attribution = (
        "Deep-ITM 'stock replacement' put approach used by momentum/trend "
        "traders for leveraged downside bets or portfolio hedges"
    )
    description = (
        "Buy a put outright to profit from (or hedge against) a decline. A "
        "delta >= 0.4 put moves meaningfully with the stock for a fraction of "
        "the capital a short-stock position would require."
    )

    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        candidates = sorted(puts(screened_contracts), key=lambda c: abs(c.delta), reverse=True)
        ideas: list[StrategyIdea] = []
        seen: set = set()
        for put in candidates:
            key = (put.expiration, put.strike)
            if key in seen:
                continue
            seen.add(key)
            debit_per_share = put.mid_price
            leg = StrategyLeg(action="buy", contract=put, quantity=1, description="Buy 1 put")
            breakeven = round(put.strike - debit_per_share, 2)
            max_profit = round(put.strike * 100 - debit_per_share * 100, 2)  # stock -> $0
            ideas.append(
                StrategyIdea(
                    strategy_key=self.key,
                    strategy_name=self.display_name,
                    trader_attribution=self.trader_attribution,
                    symbol=symbol,
                    underlying_price=underlying.price,
                    legs=[leg],
                    rationale=(
                        f"Buy the {put.expiration} ${put.strike:g} put (delta {put.delta:.2f}, "
                        f"OI {put.open_interest}) for ~${debit_per_share:.2f}/share."
                    ),
                    max_profit=max_profit,
                    max_loss=round(debit_per_share * 100, 2),
                    breakeven=[breakeven],
                    net_cost=round(debit_per_share * 100, 2),
                )
            )
            if len(ideas) >= self.max_ideas:
                break
        return ideas


register(LongPutStrategy())
