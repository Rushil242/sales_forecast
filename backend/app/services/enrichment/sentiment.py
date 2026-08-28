"""Social sentiment as a past-only covariate.

This replaces the residual-calibration fusion approach for covariate-capable models.
Instead of fitting an elasticity against forecast residuals and applying it as a
multiplier, sentiment now enters the model as an actual input column and Chronos-2
learns its relationship to demand in context. That is both simpler and stronger --
fusion had to *assume* a functional form; this does not.

``fusion.py`` remains in place for models that cannot take covariates.

Past-only, deliberately
-----------------------
Tomorrow's sentiment is not knowable today. Supplying it as known-future would leak
the future into the forecast. Two derived columns give the model the lag structure
the literature reports (3-7 days from social signal to sales) without any leakage.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.services.enrichment.base import CovariateSpec, EnrichmentProvider, Location

LOG = logging.getLogger(__name__)


class SentimentProvider(EnrichmentProvider):
    name = "sentiment"
    group = "sentiment"

    def __init__(self, daily_index: dict[str, float] | None = None) -> None:
        """``daily_index`` maps ISO date to the engagement-weighted index in [-1, 1]."""
        self.daily_index = daily_index or {}
        self._warnings: list[str] = []

    def available(self) -> bool:
        return bool(self.daily_index)

    def unavailable_reason(self) -> str:
        return "No social sentiment was harvested for this product."

    def specs(self) -> list[CovariateSpec]:
        return [
            CovariateSpec("sentiment_index", "sentiment", False, "numeric",
                          "Engagement-weighted social sentiment, -1 to +1"),
            CovariateSpec("sentiment_7d", "sentiment", False, "numeric",
                          "Seven-day rolling mean of the sentiment index"),
            CovariateSpec("sentiment_volume", "sentiment", False, "numeric",
                          "Documents harvested that day, log-damped"),
        ]

    def fetch(self, index: pd.DatetimeIndex, location: Location) -> pd.DataFrame:
        self._warnings = []
        frame = pd.DataFrame(index=index)

        if not self.daily_index:
            return frame

        import numpy as np

        observed = pd.Series(
            {pd.Timestamp(day): value for day, value in self.daily_index.items()}
        ).sort_index()

        overlap = observed.index.intersection(index)
        if len(overlap) == 0:
            # The usual case with historical datasets: sales end years before the
            # social window begins. Say so rather than emitting a column of zeros.
            self._warnings.append(
                f"Social sentiment covers {observed.index.min().date()} to "
                f"{observed.index.max().date()}, which does not overlap this series "
                f"({index.min().date()} to {index.max().date()}). Sentiment is excluded "
                "from the model rather than zero-filled."
            )
            LOG.info("Sentiment covariate skipped: no overlap with the series")
            return pd.DataFrame(index=index)

        aligned = observed.reindex(index)
        frame["sentiment_index"] = aligned.fillna(0.0)
        frame["sentiment_7d"] = (
            aligned.rolling(7, min_periods=1).mean().fillna(0.0)
        )
        # Volume is unknown here; the agent supplies it separately when available.
        frame["sentiment_volume"] = np.where(aligned.notna(), 1.0, 0.0)

        self._warnings.append(
            f"Sentiment overlaps the series on {len(overlap)} of {len(index)} days."
        )
        return frame

    def warnings(self) -> list[str]:
        return list(self._warnings)
