from __future__ import annotations

from .. import db
from ..config import get_settings
from .base import Broker, BrokerError
from .models import AccountSummary, OrderRequest, OrderResult, Position


def effective_mode() -> str:
    """Which broker mode is actually in effect right now: "paper" or "etrade".

    LIVE_TRADING_ENABLED is the one gate nothing in the app can override --
    if it's false (the default), the answer is always "paper", full stop.
    Once it's true, the in-app Paper/Live toggle (persisted via
    db.set_active_mode(), flipped from the Trading page for convenience
    while testing) decides, falling back to the server's ACTIVE_BROKER
    default until the toggle has been used at least once.
    """
    settings = get_settings()
    if not settings.live_trading_enabled:
        return "paper"
    mode = db.get_active_mode()
    if mode is None:
        mode = settings.active_broker
    return "etrade" if mode == "etrade" else "paper"


def get_broker() -> Broker:
    """Return the broker for `effective_mode()` -- see its docstring for the
    safety gate this honors."""
    if effective_mode() == "etrade":
        from .etrade_broker import ETradeBroker

        return ETradeBroker()
    from .paper_broker import PaperBroker

    return PaperBroker()


__all__ = [
    "Broker",
    "BrokerError",
    "AccountSummary",
    "OrderRequest",
    "OrderResult",
    "Position",
    "get_broker",
    "effective_mode",
]
