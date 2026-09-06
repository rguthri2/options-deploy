from __future__ import annotations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, calls, register


class CoveredCallStrategy(Strategy):
    key = "covered_call"
    display_name = "Covered Call"
    trader_attribution = "Classic income overlay popularized broadly by premium-selling educators (e.g. tastytrade)"
    description = (
        "Own 100 shares and sell a call against them. Selecting a higher-delta "
        "(>= 0.4) short call trades some upside for a much larger, more certain "
        "premium than a typical far-OTM covered call."
    )

    def scan(self, symbol: str, underlying: Underlying, screened_contracts: list[OptionContract]) -> list[StrategyIdea]:
        candidates = sorted(calls(screened_contracts), key=lambda c: c.delta)
        ideas: list[StrategyIdea] = []
        seen_expirations: set = set()
        for call in candidates:
            if call.expiration in seen_expirations:
                continue
            seen_expirations.add(call.expiration)
            credit_per_share = call.mid_price
            stock_leg = StrategyLeg(
                action="buy",
                contract=None,
                quantity=100,
                description=f"Buy 100 shares of {symbol} @ ~${underlying.price:.2f}",
            )
            call_leg = StrategyLeg(action="sell", contract=call, quantity=1, description="Sell 1 call")
            upside_per_share = call.strike - underlying.price
            max_profit = round((upside_per_share + credit_per_share) * 100, 2)
            max_loss = round((underlying.price - credit_per_share) * 100, 2)  # stock -> $0, net of premium
            breakeven = round(underlying.price - credit_per_share, 2)
            ideas.append(
                StrategyIdea(
                    strategy_key=self.key,
                    strategy_name=self.display_name,
                    trader_attribution=self.trader_attribution,
                    symbol=symbol,
                    underlying_price=underlying.price,
                    legs=[stock_leg, call_leg],
                    rationale=(
                        f"Sell the {call.expiration} ${call.strike:g} call (delta {call.delta:.2f}, "
                        f"OI {call.open_interest}) for ~${credit_per_share:.2f}/share of premium."
                    ),
                    max_profit=max_profit,
                    max_loss=max_loss,
                    breakeven=[breakeven],
                    net_cost=round(underlying.price * 100 - credit_per_share * 100, 2),
                )
            )
            if len(ideas) >= self.max_ideas:
                break
        return ideas


register(CoveredCallStrategy())
