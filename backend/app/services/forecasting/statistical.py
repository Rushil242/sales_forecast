"""Classical statistical forecasters, via Nixtla statsforecast.

These serve two distinct purposes and it is worth being explicit about both:

1. **Fallback.** If Chronos cannot be loaded (no model cache, no torch wheel for
   the platform, constrained memory) the API still returns a real forecast.
2. **Baselines.** A foundation model is only interesting if it beats the cheap
   alternatives. ``SeasonalNaive`` in particular is the reference point for MASE
   and the honest yardstick any new model has to clear.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.services.forecasting.base import Forecaster, ForecastOutput

if TYPE_CHECKING:
    from app.services.enrichment.base import CovariateFrame

LOG = logging.getLogger(__name__)

SEASON_LENGTH = 7  # daily retail data: the dominant cycle is day-of-week

# statsforecast reports symmetric prediction intervals; these map onto the
# quantile levels the rest of the system speaks.
_LEVEL_TO_QUANTILE = {("lo", 95): 0.025, ("lo", 80): 0.1, ("hi", 80): 0.9, ("hi", 95): 0.975}


class StatsForecastAdapter(Forecaster):
    """Wraps any statsforecast model behind the :class:`Forecaster` interface."""

    kind = "statistical"

    def __init__(self, name: str, model_factory, detail: str = "", *, kind: str = "statistical"):
        self.name = name
        self.kind = kind
        self.detail = detail
        self._model_factory = model_factory

    @property
    def available(self) -> bool:
        try:
            import statsforecast  # noqa: F401
        except ImportError:
            return False
        return True

    def predict(
        self,
        series: pd.Series,
        horizon: int,
        covariates: CovariateFrame | None = None,
    ) -> ForecastOutput:
        # statsforecast supports exogenous regressors for some models, but not
        # uniformly across ARIMA/ETS/Theta. Keeping these purely univariate makes
        # them a clean control group in the covariates-on vs covariates-off backtest.
        from statsforecast import StatsForecast

        frame = pd.DataFrame({
            "unique_id": "series",
            "ds": series.index,
            "y": series.values.astype("float64"),
        })

        engine = StatsForecast(
            models=[self._model_factory()],
            freq="D",
            # Single process: statsforecast's multiprocessing interacts badly with
            # an ASGI server's worker threads, and one short series does not need it.
            n_jobs=1,
        )
        predictions = engine.forecast(df=frame, h=horizon, level=[80, 95])

        # statsforecast names its output column after the model class.
        model_column = next(
            column for column in predictions.columns
            if column not in {"unique_id", "ds"} and "-lo-" not in column and "-hi-" not in column
        )
        mean = predictions[model_column].to_numpy(dtype="float64")

        quantiles: dict[float, np.ndarray] = {0.5: mean.copy()}
        for (side, level), quantile in _LEVEL_TO_QUANTILE.items():
            column = f"{model_column}-{side}-{level}"
            if column in predictions.columns:
                quantiles[quantile] = predictions[column].to_numpy(dtype="float64")

        # The 80% band is part of the Forecaster contract. If this model produced
        # no intervals at all, collapse it onto the point forecast rather than
        # inventing a spread -- a zero-width band visibly signals "no uncertainty
        # estimate available", whereas a made-up one would not.
        for required in (0.1, 0.9):
            quantiles.setdefault(required, mean.copy())

        output = ForecastOutput(
            index=self.future_index(series, horizon),
            mean=mean,
            quantiles=quantiles,
        )
        return output.enforce_monotonic_quantiles().clipped()


class SeasonalNaiveForecaster(Forecaster):
    """Repeat the last observed week, forever.

    Implemented directly rather than through statsforecast because it is the MASE
    denominator and the fallback of last resort: it must work on any series long
    enough to have one seasonal cycle, with no dependencies and no failure modes.
    Intervals come from the empirical spread of in-sample seasonal errors, widened
    with the square root of the horizon as befits a random walk.
    """

    name = "seasonal-naive"
    kind = "naive"
    detail = f"repeats the trailing {SEASON_LENGTH}-day pattern"

    def predict(
        self,
        series: pd.Series,
        horizon: int,
        covariates: CovariateFrame | None = None,
    ) -> ForecastOutput:
        values = series.values.astype("float64")
        period = min(SEASON_LENGTH, len(values))
        last_cycle = values[-period:]
        mean = np.array([last_cycle[i % period] for i in range(horizon)], dtype="float64")

        if len(values) > period:
            residual_sd = float(np.std(values[period:] - values[:-period]))
        else:
            residual_sd = float(np.std(values))
        if residual_sd == 0:
            residual_sd = max(float(np.mean(values)) * 0.1, 1e-6)

        widening = np.sqrt(np.arange(1, horizon + 1) / period)
        spread = residual_sd * widening
        quantiles = {
            0.025: mean - 1.960 * spread,
            0.100: mean - 1.282 * spread,
            0.500: mean.copy(),
            0.900: mean + 1.282 * spread,
            0.975: mean + 1.960 * spread,
        }
        output = ForecastOutput(
            index=self.future_index(series, horizon), mean=mean, quantiles=quantiles
        )
        return output.enforce_monotonic_quantiles().clipped()


def _auto_arima():
    from statsforecast.models import AutoARIMA

    return AutoARIMA(season_length=SEASON_LENGTH)


def _auto_ets():
    from statsforecast.models import AutoETS

    return AutoETS(season_length=SEASON_LENGTH)


def _theta():
    from statsforecast.models import DynamicOptimizedTheta

    return DynamicOptimizedTheta(season_length=SEASON_LENGTH)


def build_statistical_forecasters() -> list[Forecaster]:
    return [
        StatsForecastAdapter(
            "auto-arima", _auto_arima,
            "Hyndman-Khandakar stepwise ARIMA search, weekly seasonality",
        ),
        StatsForecastAdapter(
            "auto-ets", _auto_ets,
            "automatic error/trend/seasonal exponential smoothing",
        ),
        StatsForecastAdapter(
            "theta", _theta,
            "dynamic optimised Theta, strong M4 benchmark performer",
        ),
        SeasonalNaiveForecaster(),
    ]
