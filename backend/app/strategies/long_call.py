from __future__ import annotations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, calls, register


class LongCallStrategy(Strategy):
    key = "long_call"
    display_name = "Long Call (Stock Replacement)"
    trader_attribution = (
        "Deep-ITM 'stock replacement' approach used by momentum/trend traders "
        "to get leveraged upside exposure for a fraction of the capital of owning shares"
    )
    description = (
        "Buy a call outright instead of shares. A delta >= 0.4 call moves "
        "meaningfully with the stock while still costing far less than 100 shares."
    )

    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        candidates = sorted(calls(screened_contracts), key=lambda c: c.delta, reverse=True)
        ideas: list[StrategyIdea] = []
        seen: set = set()
        for call in candidates:
            key = (call.expiration, call.strike)
            if key in seen:
                continue
            seen.add(key)
            debit_per_share = call.mid_price
            leg = StrategyLeg(action="buy", contract=call, quantity=1, description="Buy 1 call")
            breakeven = round(call.strike + debit_per_share, 2)
            ideas.append(
                StrategyIdea(
                    strategy_key=self.key,
                    strategy_name=self.display_name,
                    trader_attribution=self.trader_attribution,
                    symbol=symbol,
                    underlying_price=underlying.price,
                    legs=[leg],
                    rationale=(
                        f"Buy the {call.expiration} ${call.strike:g} call (delta {call.delta:.2f}, "
                        f"OI {call.open_interest}) for ~${debit_per_share:.2f}/share."
                    ),
                    max_profit=None,  # theoretically unlimited upside
                    max_loss=round(debit_per_share * 100, 2),
                    breakeven=[breakeven],
                    net_cost=round(debit_per_share * 100, 2),
                )
            )
            if len(ideas) >= self.max_ideas:
                break
        return ideas


register(LongCallStrategy())
