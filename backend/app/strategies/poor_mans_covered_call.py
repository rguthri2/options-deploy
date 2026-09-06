from __future__ import annotations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, calls, group_by_expiration, register


class PoorMansCoveredCallStrategy(Strategy):
    key = "poor_mans_covered_call"
    display_name = "Poor Man's Covered Call"
    trader_attribution = "Capital-efficient covered-call alternative popularized in the LEAPS/diagonal-spread trading community"
    description = (
        "Replace 100 shares with a deep-dated, deep-ITM long call (a LEAPS "
        "stock surrogate), then sell near-term calls against it for income -- "
        "the same idea as a covered call at a fraction of the capital."
    )

    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        by_expiration = group_by_expiration(calls(screened_contracts))
        expirations = list(by_expiration.keys())
        if len(expirations) < 2:
            return []

        long_expiration = expirations[-1]  # furthest dated => LEAPS-like leg
        long_candidates = sorted(by_expiration[long_expiration], key=lambda c: c.delta, reverse=True)
        if not long_candidates:
            return []

        ideas: list[StrategyIdea] = []
        for long_leg in long_candidates[:2]:
            for short_expiration in expirations[:-1]:
                short_candidates = [
                    c
                    for c in sorted(by_expiration[short_expiration], key=lambda c: c.delta)
                    if c.strike > long_leg.strike
                ]
                if not short_candidates:
                    continue
                short_leg = short_candidates[0]  # lowest qualifying delta => most OTM allowed by the screen

                net_cost = round(long_leg.ask - short_leg.bid, 2)
                if net_cost <= 0:
                    continue
                width = round(short_leg.strike - long_leg.strike, 2)
                # Approximate payoff at the short expiration, treating the long
                # LEAPS leg's remaining time value as roughly unchanged -- the
                # standard simplified way this diagonal is quoted.
                max_profit_est = round(width * 100 - net_cost * 100, 2)
                max_loss_est = round(net_cost * 100, 2)
                breakeven_est = round(long_leg.strike + net_cost, 2)

                ideas.append(
                    StrategyIdea(
                        strategy_key=self.key,
                        strategy_name=self.display_name,
                        trader_attribution=self.trader_attribution,
                        symbol=symbol,
                        underlying_price=underlying.price,
                        legs=[
                            StrategyLeg(
                                action="buy",
                                contract=long_leg,
                                quantity=1,
                                description=f"Buy 1 LEAPS call, {long_expiration}",
                            ),
                            StrategyLeg(
                                action="sell",
                                contract=short_leg,
                                quantity=1,
                                description=f"Sell 1 near-term call, {short_expiration}",
                            ),
                        ],
                        rationale=(
                            f"Buy the {long_expiration} ${long_leg.strike:g} call (delta {long_leg.delta:.2f}) as a "
                            f"stock surrogate, then sell the {short_expiration} ${short_leg.strike:g} call "
                            f"(delta {short_leg.delta:.2f}) for income. Net debit ~${net_cost:.2f}/share. "
                            "Profit/loss figures are approximate: they assume the LEAPS leg's own time value "
                            "is roughly unchanged at the short call's expiration."
                        ),
                        max_profit=max_profit_est,
                        max_loss=max_loss_est,
                        breakeven=[breakeven_est],
                        net_cost=round(net_cost * 100, 2),
                    )
                )
                if len(ideas) >= self.max_ideas:
                    return ideas
        return ideas


register(PoorMansCoveredCallStrategy())
