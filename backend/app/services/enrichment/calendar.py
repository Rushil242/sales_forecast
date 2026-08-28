"""Deterministic calendar covariates.

No network, no key, never fails, and known-future by definition -- every value here
is a property of the date itself. That makes this the baseline covariate group: if
the backtest shows calendar features alone improve accuracy, the covariate machinery
is working before any external API is involved.

Cyclical encoding
-----------------
Day-of-week and month are encoded as sine/cosine pairs rather than raw integers.
Given raw numbers a model sees December (12) as maximally distant from January (1),
when they are adjacent. The sin/cos pair puts them next to each other on a circle.

The payday feature
------------------
Indian salaried income lands on roughly the 1st and the 7th, and FMCG/apparel demand
visibly follows it. This is a real pattern in Indian retail rather than a generic
calendar feature, and it costs nothing to include.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.enrichment.base import CovariateSpec, EnrichmentProvider, Location


class CalendarProvider(EnrichmentProvider):
    name = "calendar"
    group = "calendar"

    def specs(self) -> list[CovariateSpec]:
        return [
            CovariateSpec("dow_sin", "calendar", True, "numeric",
                          "Day of week, sine component of its cyclical encoding"),
            CovariateSpec("dow_cos", "calendar", True, "numeric",
                          "Day of week, cosine component"),
            CovariateSpec("month_sin", "calendar", True, "numeric",
                          "Month of year, sine component"),
            CovariateSpec("month_cos", "calendar", True, "numeric",
                          "Month of year, cosine component"),
            CovariateSpec("is_weekend", "calendar", True, "numeric",
                          "1 on Saturday or Sunday"),
            CovariateSpec("is_month_end", "calendar", True, "numeric",
                          "1 in the last three days of the month"),
            CovariateSpec("days_from_payday", "calendar", True, "numeric",
                          "Days from the nearest Indian payday (1st or 7th), capped at 10"),
        ]

    def fetch(self, index: pd.DatetimeIndex, location: Location) -> pd.DataFrame:
        frame = pd.DataFrame(index=index)

        dow = index.dayofweek.to_numpy()
        frame["dow_sin"] = np.sin(2 * np.pi * dow / 7)
        frame["dow_cos"] = np.cos(2 * np.pi * dow / 7)

        month = index.month.to_numpy()
        frame["month_sin"] = np.sin(2 * np.pi * month / 12)
        frame["month_cos"] = np.cos(2 * np.pi * month / 12)

        frame["is_weekend"] = (dow >= 5).astype(float)
        frame["is_month_end"] = (index.day >= index.days_in_month - 2).astype(float)

        day = index.day.to_numpy()
        frame["days_from_payday"] = np.minimum(
            np.minimum(np.abs(day - 1), np.abs(day - 7)), 10
        ).astype(float)

        return frame

    def warnings(self) -> list[str]:
        return []
