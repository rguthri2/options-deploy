"""App-wide settings, sourced from environment variables so deployment
(mock data vs. live yfinance data, screening thresholds, auth, broker mode)
can be changed without editing code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from .models import ScreeningCriteria


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_provider: str  # "mock" | "yfinance"
    min_open_interest: int
    min_abs_delta: float
    min_days_to_expiration: int

    # --- Auth ---
    secret_key: str
    admin_username: str
    admin_password_hash: str  # empty string => auth is unset; app should refuse to serve
    cookie_secure: bool  # set False only for temporary plain-http local testing
    session_max_age_seconds: int

    # --- Trading / brokers ---
    db_path: str
    active_broker: str  # "paper" | "etrade"
    live_trading_enabled: bool  # master safety switch; false => every order is forced to paper
    paper_starting_cash: float
    etrade_consumer_key: str
    etrade_consumer_secret: str
    etrade_sandbox: bool

    def screening_criteria(self) -> ScreeningCriteria:
        return ScreeningCriteria(
            min_open_interest=self.min_open_interest,
            min_abs_delta=self.min_abs_delta,
            min_days_to_expiration=self.min_days_to_expiration,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings(
        data_provider=os.environ.get("DATA_PROVIDER", "mock").lower(),
        min_open_interest=int(os.environ.get("MIN_OPEN_INTEREST", "100")),
        min_abs_delta=float(os.environ.get("MIN_ABS_DELTA", "0.4")),
        min_days_to_expiration=int(os.environ.get("MIN_DAYS_TO_EXPIRATION", "14")),
        secret_key=os.environ.get("SECRET_KEY", ""),
        admin_username=os.environ.get("ADMIN_USERNAME", ""),
        admin_password_hash=os.environ.get("ADMIN_PASSWORD_HASH", ""),
        cookie_secure=_bool_env("COOKIE_SECURE", True),
        session_max_age_seconds=int(os.environ.get("SESSION_MAX_AGE_SECONDS", str(12 * 3600))),
        db_path=os.environ.get("DB_PATH", "options_app.db"),
        active_broker=os.environ.get("ACTIVE_BROKER", "paper").lower(),
        live_trading_enabled=_bool_env("LIVE_TRADING_ENABLED", False),
        paper_starting_cash=float(os.environ.get("PAPER_STARTING_CASH", "100000")),
        etrade_consumer_key=os.environ.get("ETRADE_CONSUMER_KEY", ""),
        etrade_consumer_secret=os.environ.get("ETRADE_CONSUMER_SECRET", ""),
        etrade_sandbox=_bool_env("ETRADE_SANDBOX", True),
    )
