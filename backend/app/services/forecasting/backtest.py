"""Rolling-origin backtesting.

This is the module that turns "the chart looks plausible" into a defensible
accuracy claim. Evaluation follows the standard rolling-origin (walk-forward)
protocol: repeatedly cut the series at an earlier point, forecast forward with
only the data available at that cut, and score against the held-out actuals.

Crucially, no model ever sees data past its own cut point, so there is no
leakage, and every model is scored on identical windows.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.schemas.forecast import BacktestResult, MetricSet
from app.services.enrichment.base import CovariateFrame
from app.services.forecasting.base import Forecaster
from app.services.forecasting.metrics import (
    interval_coverage,
    mae,
    mape,
    mase,
    rmse,
    smape,
)

LOG = logging.getLogger(__name__)


@dataclass
class WindowScore:
    model: str
    window: int
    cutoff: pd.Timestamp
    mae: float
    rmse: float
    mape: float | None
    smape: float
    mase: float | None
    coverage_80: float


def plan_windows(n_observations: int, horizon: int, requested_windows: int) -> list[int]:
    """Choose cut points, newest first.

    Each window needs ``horizon`` days of holdout after it and enough history
    before it to fit anything meaningful. Windows are spaced one horizon apart so
    their holdout periods do not overlap.
    """
    min_train = max(2 * horizon, 60)
    cutoffs: list[int] = []
    for i in range(requested_windows):
        cutoff = n_observations - horizon * (i + 1)
        if cutoff < min_train:
            break
        cutoffs.append(cutoff)
    return cutoffs


def _score(
    model_name: str,
    window: int,
    cutoff_date: pd.Timestamp,
    actual: np.ndarray,
    output,
    training: np.ndarray,
) -> WindowScore:
    return WindowScore(
        model=model_name,
        window=window,
        cutoff=cutoff_date,
        mae=mae(actual, output.mean),
        rmse=rmse(actual, output.mean),
        mape=mape(actual, output.mean),
        smape=smape(actual, output.mean),
        mase=mase(actual, output.mean, training),
        coverage_80=interval_coverage(actual, output.quantiles[0.1], output.quantiles[0.9]),
    )


def _aggregate(scores: list[WindowScore]) -> MetricSet:
    """Average each metric across windows, ignoring windows where it was undefined."""

    def mean_of(values: list[float | None]) -> float | None:
        present = [v for v in values if v is not None and np.isfinite(v)]
        return float(np.mean(present)) if present else None

    return MetricSet(
        mae=round(mean_of([s.mae for s in scores]) or 0.0, 3),
        rmse=round(mean_of([s.rmse for s in scores]) or 0.0, 3),
        mape=(lambda v: round(v, 2) if v is not None else None)(mean_of([s.mape for s in scores])),
        smape=round(mean_of([s.smape for s in scores]) or 0.0, 2),
        mase=(lambda v: round(v, 3) if v is not None else None)(mean_of([s.mase for s in scores])),
        coverage_80=round(mean_of([s.coverage_80 for s in scores]) or 0.0, 3),
    )


def run_backtest(
    series: pd.Series,
    forecasters: list[Forecaster],
    horizon: int,
    windows: int,
    covariates: CovariateFrame | None = None,
) -> BacktestResult | None:
    """Score every forecaster over the same rolling-origin windows.

    Returns ``None`` when the series is too short to carve out even one window --
    the honest answer in that case is "we cannot measure this", not a fabricated
    accuracy figure.
    """
    cutoffs = plan_windows(len(series), horizon, windows)
    if not cutoffs:
        LOG.info(
            "Series of %d days is too short to backtest a %d-day horizon; skipping",
            len(series), horizon,
        )
        return None

    usable = [f for f in forecasters if f.available]
    scores: dict[str, list[WindowScore]] = {}
    started = time.perf_counter()

    for window_number, cutoff in enumerate(cutoffs, start=1):
        train = series.iloc[:cutoff]
        actual = series.iloc[cutoff:cutoff + horizon].values.astype("float64")
        if actual.size < horizon:
            continue

        for forecaster in usable:
            try:
                # Only covariate-capable models receive the external signals; the
                # univariate models are the control group, so handing them anything
                # would make the comparison meaningless.
                window_cov = covariates if forecaster.supports_covariates else None
                output = forecaster.predict(train, horizon, window_cov)
            except Exception as exc:
                # One model failing on one window must not void the whole comparison.
                LOG.warning(
                    "Backtest window %d failed for %s: %s", window_number, forecaster.name, exc
                )
                continue
            scores.setdefault(forecaster.name, []).append(
                _score(
                    forecaster.name, window_number, series.index[cutoff],
                    actual, output, train.values.astype("float64"),
                )
            )

    if not scores:
        return None

    metrics_by_model = {name: _aggregate(window_scores) for name, window_scores in scores.items()}

    # Rank on MASE where available (scale-free), else fall back to RMSE.
    def rank_key(item: tuple[str, MetricSet]) -> tuple[int, float]:
        metrics = item[1]
        return (0, metrics.mase) if metrics.mase is not None else (1, metrics.rmse)

    best_model = min(metrics_by_model.items(), key=rank_key)[0]

    improvement = None
    naive = metrics_by_model.get("seasonal-naive")
    best = metrics_by_model[best_model]
    if naive and naive.rmse > 0 and best_model != "seasonal-naive":
        improvement = round((naive.rmse - best.rmse) / naive.rmse * 100, 2)

    elapsed = time.perf_counter() - started
    LOG.info(
        "Backtest complete: %d windows x %d models in %.1fs; best=%s",
        len(cutoffs), len(scores), elapsed, best_model,
    )

    return BacktestResult(
        windows=len(cutoffs),
        horizon=horizon,
        metrics_by_model=metrics_by_model,
        best_model=best_model,
        improvement_over_naive_pct=improvement,
        note=(
            f"Rolling-origin evaluation over {len(cutoffs)} non-overlapping "
            f"{horizon}-day windows. Models ranked by MASE; a MASE below 1.0 beats "
            "a seasonal-naive forecast."
            + (
                " Covariate-capable models received the selected external signals; "
                "the univariate models are the control group."
                if covariates is not None and not covariates.is_empty else ""
            )
        ),
    )
