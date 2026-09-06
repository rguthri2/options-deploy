from __future__ import annotations

from ..config import get_settings
from .base import Broker, BrokerError
from .models import AccountSummary, OrderRequest, OrderResult, Position


def get_broker() -> Broker:
    """Return the active broker, honoring the LIVE_TRADING_ENABLED safety gate.

    ACTIVE_BROKER selects which broker *would* handle live orders, but if
    LIVE_TRADING_ENABLED is false (the default), every request is routed to
    the paper broker regardless -- a misconfigured or forgotten env var can
    never accidentally enable real trading.
    """
    settings = get_settings()
    if settings.active_broker == "etrade" and settings.live_trading_enabled:
        from .etrade_broker import ETradeBroker

        return ETradeBroker()
    from .paper_broker import PaperBroker

    return PaperBroker()


__all__ = ["Broker", "BrokerError", "AccountSummary", "OrderRequest", "OrderResult", "Position", "get_broker"]
