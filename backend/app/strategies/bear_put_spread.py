from __future__ import annotations

from itertools import combinations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, group_by_expiration, puts, register


class BearPutSpreadStrategy(Strategy):
    key = "bear_put_spread"
    display_name = "Bear Put Debit Spread"
    trader_attribution = "Defined-risk bearish spread widely taught by tastytrade and other spread-trading educators"
    description = (
        "Buy a higher-strike, higher-delta put and sell a lower-strike put in "
        "the same expiration to reduce cost/risk versus an outright long put, "
        "in exchange for a capped payout."
    )

    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        ideas: list[StrategyIdea] = []
        for expiration, contracts in group_by_expiration(puts(screened_contracts)).items():
            by_strike = sorted(contracts, key=lambda c: c.strike, reverse=True)
            for long_leg, short_leg in combinations(by_strike, 2):
                if short_leg.strike >= long_leg.strike:
                    continue
                if abs(long_leg.delta) <= abs(short_leg.delta):
                    continue
                debit_per_share = round(long_leg.ask - short_leg.bid, 2)
                if debit_per_share <= 0:
                    continue
                width = round(long_leg.strike - short_leg.strike, 2)
                max_profit = round((width - debit_per_share) * 100, 2)
                if max_profit <= 0:
                    continue
                max_loss = round(debit_per_share * 100, 2)
                breakeven = round(long_leg.strike - debit_per_share, 2)
                ideas.append(
                    StrategyIdea(
                        strategy_key=self.key,
                        strategy_name=self.display_name,
                        trader_attribution=self.trader_attribution,
                        symbol=symbol,
                        underlying_price=underlying.price,
                        legs=[
                            StrategyLeg(action="buy", contract=long_leg, quantity=1, description="Buy higher-strike put"),
                            StrategyLeg(action="sell", contract=short_leg, quantity=1, description="Sell lower-strike put"),
                        ],
                        rationale=(
                            f"Buy the {expiration} ${long_leg.strike:g} put (delta {long_leg.delta:.2f}) and sell "
                            f"the ${short_leg.strike:g} put (delta {short_leg.delta:.2f}) for a ${debit_per_share:.2f}/share "
                            f"debit, risking ${max_loss:,.0f} to make up to ${max_profit:,.0f}."
                        ),
                        max_profit=max_profit,
                        max_loss=max_loss,
                        breakeven=[breakeven],
                        net_cost=round(debit_per_share * 100, 2),
                    )
                )
        ideas.sort(key=lambda i: (i.max_profit or 0) / max(i.max_loss or 1, 1), reverse=True)
        return ideas[: self.max_ideas]


register(BearPutSpreadStrategy())
