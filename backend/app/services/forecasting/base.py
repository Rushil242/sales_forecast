"""Forecaster interface shared by the foundation model and the statistical baselines.

A note on interval levels
-------------------------
Not every model can produce every quantile. Chronos-Bolt has fixed quantile heads
trained on 0.1 through 0.9, so asking it for 0.025 returns its 0.1 head clamped --
a 95% interval that is really an 80% interval wearing a different label. The
statistical models, by contrast, derive intervals analytically and can produce
any level.

Rather than paper over that, the 80% interval is treated as the universal
contract every model must honour, and the 95% interval is optional: models that
cannot produce it honestly simply omit it, and the API reports ``null`` instead of
a number that would overstate what is known.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from app.services.enrichment.base import CovariateFrame

# Required of every forecaster: an 80% interval plus the median.
CORE_QUANTILES: tuple[float, ...] = (0.1, 0.5, 0.9)
# Served only by models that genuinely support them.
EXTENDED_QUANTILES: tuple[float, ...] = (0.025, 0.975)


@dataclass
class ForecastOutput:
    """Quantile forecast over a future index.

    ``quantiles`` maps a level to an array of length ``len(index)``. It must
    contain at least :data:`CORE_QUANTILES`; anything further is a bonus the
    caller may or may not find present.
    """

    index: pd.DatetimeIndex
    mean: np.ndarray
    quantiles: dict[float, np.ndarray]

    def __post_init__(self) -> None:
        horizon = len(self.index)
        if self.mean.shape != (horizon,):
            raise ValueError(f"mean has shape {self.mean.shape}, expected ({horizon},)")
        missing = [q for q in CORE_QUANTILES if q not in self.quantiles]
        if missing:
            raise ValueError(f"forecast is missing required quantiles: {missing}")
        for level, values in self.quantiles.items():
            if values.shape != (horizon,):
                raise ValueError(
                    f"quantile {level} has shape {values.shape}, expected ({horizon},)"
                )

    @property
    def has_95(self) -> bool:
        return all(q in self.quantiles for q in EXTENDED_QUANTILES)

    def clipped(self, lower: float = 0.0) -> ForecastOutput:
        """Clamp to a floor. Unit sales cannot be negative."""
        return ForecastOutput(
            index=self.index,
            mean=np.clip(self.mean, lower, None),
            quantiles={q: np.clip(v, lower, None) for q, v in self.quantiles.items()},
        )

    def enforce_monotonic_quantiles(self) -> ForecastOutput:
        """Guarantee the quantiles are non-decreasing in level at every step.

        Independent quantile heads can cross, especially on short or noisy series.
        Sorting across the quantile axis is the standard, distribution-preserving fix.
        """
        levels = sorted(self.quantiles)
        stacked = np.sort(np.vstack([self.quantiles[level] for level in levels]), axis=0)
        return ForecastOutput(
            index=self.index,
            mean=self.mean,
            quantiles={level: stacked[i] for i, level in enumerate(levels)},
        )


class Forecaster(ABC):
    """A forecasting strategy: give it history, get back a horizon."""

    name: str = "base"
    kind: str = "statistical"
    detail: str = ""

    #: Whether this model can consume exogenous covariates. Models that cannot
    #: simply ignore the argument, so callers never have to branch.
    supports_covariates: bool = False

    @abstractmethod
    def predict(
        self,
        series: pd.Series,
        horizon: int,
        covariates: CovariateFrame | None = None,
    ) -> ForecastOutput:
        """Forecast ``horizon`` steps beyond the end of ``series``.

        ``covariates`` is accepted by every implementation for a uniform call site,
        but only honoured where :attr:`supports_covariates` is true. Silently
        ignoring it elsewhere is deliberate: the alternative is every caller
        checking capability before every call.
        """

    @property
    def available(self) -> bool:
        """Whether this forecaster can run right now (model downloaded, deps present)."""
        return True

    @staticmethod
    def future_index(series: pd.Series, horizon: int) -> pd.DatetimeIndex:
        start = series.index[-1] + pd.Timedelta(days=1)
        return pd.date_range(start=start, periods=horizon, freq="D")

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name, "kind": self.kind, "detail": self.detail,
            "supports_covariates": self.supports_covariates,
        }
