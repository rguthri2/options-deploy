from __future__ import annotations

from ..models import OptionContract, StrategyIdea, StrategyLeg, Underlying
from .base import Strategy, puts, register


class CashSecuredPutStrategy(Strategy):
    key = "cash_secured_put"
    display_name = "Cash-Secured Put"
    trader_attribution = "Premium-selling entry popularized by the tastytrade/'sell high-probability premium' community"
    description = (
        "Sell a put backed by cash equal to 100x the strike. A higher-delta "
        "(>= 0.4) short put collects a much richer premium in exchange for a "
        "meaningfully higher chance of being assigned the stock."
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
            put_leg = StrategyLeg(action="sell", contract=put, quantity=1, description="Sell 1 put")
            cash_required = round(put.strike * 100, 2)
            max_profit = round(credit_per_share * 100, 2)
            max_loss = round(cash_required - credit_per_share * 100, 2)  # stock -> $0
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
                        f"Sell the {put.expiration} ${put.strike:g} put (delta {put.delta:.2f}, "
                        f"OI {put.open_interest}) for ~${credit_per_share:.2f}/share, securing "
                        f"${cash_required:,.0f} cash in case of assignment."
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


register(CashSecuredPutStrategy())
