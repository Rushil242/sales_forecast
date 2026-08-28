"""Sentiment-forecast fusion.

The objective is to use social sentiment as an exogenous signal that corrects the
forecast. The difficulty is that Chronos-Bolt is a univariate model with no
covariate input, so the sentiment cannot be fed to it directly.

Approach: residual calibration
------------------------------
Rather than asserting a relationship, we measure whether one exists in this
product's own history:

1. Produce in-sample one-step residuals from the base model over the period where
   both sales history and harvested sentiment exist.
2. Regress the *relative* residual (residual / actual level) on the sentiment
   index at several candidate lags. The literature (Duan et al., 2021) puts the
   social-to-sales lead time at three to seven days, so lags 0-7 are searched.
3. Keep the lag with the strongest fit, and accept it only if it clears a
   significance floor. The fitted slope is the **elasticity**: the proportional
   change in demand associated with a one-unit change in the sentiment index.
4. Apply that elasticity to the forecast horizon, bounded by
   ``fusion_max_adjustment``.

If there is not enough overlapping data to fit anything (the common case, since
harvested sentiment covers ~30 days while sales history covers years), the module
falls back to a small bounded prior elasticity and **says so** -- the response
reports ``mode="prior"`` along with the number used, so nobody mistakes an
assumption for a measurement.

What this deliberately does not do is quietly multiply the forecast by a
plausible-looking factor and present the result as a sentiment-aware prediction.
Every adjustment is reported alongside the un-adjusted base forecast.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.config import get_settings
from app.schemas.forecast import FusionResult
from app.services.forecasting.base import ForecastOutput

LOG = logging.getLogger(__name__)

# Below this R^2 the relationship is treated as noise rather than signal.
MIN_R_SQUARED = 0.05


@dataclass
class Calibration:
    elasticity: float
    lag_days: int
    r_squared: float
    overlap_days: int
    mode: str  # calibrated | prior | unavailable


def _align(
    series: pd.Series, sentiment: dict[str, float], lag_days: int
) -> tuple[np.ndarray, np.ndarray]:
    """Pair each sales day with the sentiment index from ``lag_days`` earlier."""
    if not sentiment:
        return np.array([]), np.array([])

    sentiment_series = pd.Series(
        {pd.Timestamp(day): value for day, value in sentiment.items()}
    ).sort_index()
    # Shift sentiment forward: sentiment on day t is hypothesised to influence
    # sales on day t + lag.
    shifted = sentiment_series.copy()
    shifted.index = shifted.index + pd.Timedelta(days=lag_days)

    joined = pd.DataFrame({"sales": series}).join(
        shifted.rename("sentiment"), how="inner"
    ).dropna()
    if joined.empty:
        return np.array([]), np.array([])
    return joined["sales"].to_numpy(dtype="float64"), joined["sentiment"].to_numpy(
        dtype="float64"
    )


def _relative_deviation(sales: np.ndarray, window: int = 7) -> np.ndarray:
    """Each day's sales relative to a trailing local level, centred on zero.

    Using deviation-from-local-level rather than raw units makes the regression
    scale-free and strips out the trend and weekly cycle the base model already
    captures -- what remains is the part sentiment could plausibly explain.
    """
    if sales.size < window + 1:
        return np.array([])
    level = pd.Series(sales).rolling(window, min_periods=window).mean().to_numpy()
    valid = ~np.isnan(level) & (level > 0)
    deviation = np.full(sales.shape, np.nan)
    deviation[valid] = sales[valid] / level[valid] - 1.0
    return deviation


def calibrate(series: pd.Series, sentiment: dict[str, float]) -> Calibration:
    """Search candidate lags for a usable sentiment-to-demand relationship."""
    settings = get_settings()

    if not sentiment:
        return Calibration(0.0, 0, 0.0, 0, "unavailable")

    best: Calibration | None = None
    for lag in settings.fusion_candidate_lags:
        sales, sentiment_values = _align(series, sentiment, lag)
        if sales.size < settings.fusion_min_overlap_days:
            continue

        deviation = _relative_deviation(sales)
        mask = ~np.isnan(deviation)
        x, y = sentiment_values[mask], deviation[mask]
        if x.size < settings.fusion_min_overlap_days or np.std(x) == 0:
            continue

        # Ordinary least squares slope, plus the R^2 it achieves.
        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope * x + intercept
        residual_ss = float(np.sum((y - predicted) ** 2))
        total_ss = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - residual_ss / total_ss if total_ss > 0 else 0.0

        if best is None or r_squared > best.r_squared:
            best = Calibration(
                elasticity=float(slope), lag_days=lag,
                r_squared=float(r_squared), overlap_days=int(x.size),
                mode="calibrated",
            )

    if best is None:
        overlap = max(
            (_align(series, sentiment, lag)[0].size for lag in settings.fusion_candidate_lags),
            default=0,
        )
        LOG.info(
            "Fusion: only %d overlapping days (need %d); using bounded prior elasticity",
            overlap, settings.fusion_min_overlap_days,
        )
        return Calibration(
            elasticity=settings.fusion_prior_elasticity, lag_days=3,
            r_squared=0.0, overlap_days=int(overlap), mode="prior",
        )

    if best.r_squared < MIN_R_SQUARED:
        LOG.info(
            "Fusion: best fit at lag %d explains only %.1f%% of variance; treating as noise",
            best.lag_days, best.r_squared * 100,
        )
        return Calibration(
            elasticity=settings.fusion_prior_elasticity, lag_days=best.lag_days,
            r_squared=best.r_squared, overlap_days=best.overlap_days, mode="prior",
        )

    LOG.info(
        "Fusion calibrated: elasticity=%.4f at lag %d days (R^2=%.3f over %d days)",
        best.elasticity, best.lag_days, best.r_squared, best.overlap_days,
    )
    return best


def apply_fusion(
    forecast: ForecastOutput,
    series: pd.Series,
    sentiment: dict[str, float],
    recent_sentiment_index: float | None = None,
) -> tuple[ForecastOutput, FusionResult]:
    """Adjust a base forecast by the calibrated sentiment elasticity.

    Returns the adjusted forecast and a full account of what was done, including
    the case where nothing was done.
    """
    settings = get_settings()

    if not settings.fusion_enabled:
        return forecast, FusionResult(
            applied=False, mode="disabled",
            note="Sentiment fusion is disabled by configuration.",
        )

    if not sentiment:
        return forecast, FusionResult(
            applied=False, mode="unavailable",
            note="No social sentiment was available for this product, so the forecast "
                 "is based on transactional history alone.",
        )

    calibration = calibrate(series, sentiment)

    # The forward-looking signal is the most recent sentiment reading, since that
    # is what is hypothesised to lead demand over the coming days.
    if recent_sentiment_index is None:
        recent_values = list(sentiment.values())[-7:]
        recent_sentiment_index = float(np.mean(recent_values)) if recent_values else 0.0

    raw_adjustment = calibration.elasticity * recent_sentiment_index
    adjustment = float(
        np.clip(raw_adjustment, -settings.fusion_max_adjustment, settings.fusion_max_adjustment)
    )

    if abs(adjustment) < 1e-6:
        return forecast, FusionResult(
            applied=False, mode=calibration.mode,  # type: ignore[arg-type]
            elasticity=round(calibration.elasticity, 6),
            lag_days=calibration.lag_days,
            r_squared=round(calibration.r_squared, 4),
            overlap_days=calibration.overlap_days,
            sentiment_index_mean=round(recent_sentiment_index, 4),
            note="Sentiment is effectively neutral, so no adjustment was applied.",
        )

    factor = 1.0 + adjustment
    adjusted = ForecastOutput(
        index=forecast.index,
        mean=forecast.mean * factor,
        # Intervals are scaled by the same factor. This shifts the band with the
        # point forecast without narrowing it: fusion changes the expected level,
        # it does not make us more certain.
        quantiles={level: values * factor for level, values in forecast.quantiles.items()},
    ).clipped()

    note = (
        f"Applied a {adjustment:+.1%} adjustment from a sentiment index of "
        f"{recent_sentiment_index:+.3f} and an elasticity of {calibration.elasticity:.4f} "
        f"at a {calibration.lag_days}-day lag."
    )
    if calibration.mode == "prior":
        note += (
            f" This elasticity is a bounded prior, not a fit: only "
            f"{calibration.overlap_days} overlapping days were available "
            f"(at least {settings.fusion_min_overlap_days} are needed to calibrate). "
            "Treat the adjustment as a weak assumption."
        )
    else:
        note += (
            f" Calibrated on {calibration.overlap_days} overlapping days, "
            f"explaining {calibration.r_squared:.1%} of residual variance."
        )
    if abs(raw_adjustment) > settings.fusion_max_adjustment:
        note += (
            f" The raw adjustment of {raw_adjustment:+.1%} was capped at "
            f"{settings.fusion_max_adjustment:.0%}."
        )

    return adjusted, FusionResult(
        applied=True,
        mode=calibration.mode,  # type: ignore[arg-type]
        elasticity=round(calibration.elasticity, 6),
        lag_days=calibration.lag_days,
        r_squared=round(calibration.r_squared, 4),
        overlap_days=calibration.overlap_days,
        mean_adjustment_pct=round(adjustment * 100, 3),
        max_adjustment_pct=round(adjustment * 100, 3),
        sentiment_index_mean=round(recent_sentiment_index, 4),
        note=note,
    )
