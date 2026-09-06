"""App-wide settings, sourced from environment variables so deployment
(mock data vs. live yfinance data, screening thresholds) can be changed
without editing code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from .models import ScreeningCriteria


@dataclass(frozen=True)
class Settings:
    data_provider: str  # "mock" | "yfinance"
    min_open_interest: int
    min_abs_delta: float
    min_days_to_expiration: int

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
    )
