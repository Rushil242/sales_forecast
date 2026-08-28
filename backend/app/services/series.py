"""Daily series construction and data-quality assessment.

Design note -- what changed and why
-----------------------------------
The previous implementation, when a product had too little history, prepended
~120 days of *invented* observations generated from a seeded RNG with hard-coded
weekly weights, then injected those same weights back into the output whenever
the fitted model produced a flat forecast. The consequence was that the headline
numbers (notably a "47% weekend uplift") were properties of the padding constants,
not of the data.

This module does the opposite: it measures what the series can actually support
and says so. A series below ``min_observations`` raises ``InsufficientDataError``
rather than being padded, and everything between that floor and
``recommended_observations`` is served with an explicit warning attached to the
response.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.config import get_settings
from app.core.errors import InsufficientDataError, ProductNotFoundError
from app.schemas.forecast import DataQuality, DataQualityLevel
from app.services.ingestion import Dataset

LOG = logging.getLogger(__name__)

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def build_daily_series(
    dataset: Dataset,
    product_name: str | None = None,
    region: str | None = None,
    filters: dict[str, str] | None = None,
) -> pd.Series:
    """Aggregate transactions into a gapless daily units series.

    Days inside the observed window with no transactions are genuine zero-demand
    days and are filled with 0. No days are invented outside the observed window.

    ``filters`` selects a *group* rather than a single product -- ``{"category":
    "Upper Wear"}`` sums every product in that category into one series. This is
    what lets a buyer forecast a whole department, which is usually the level they
    actually purchase at. Aggregating before forecasting is deliberate and is not
    the same as forecasting each product and adding the results: demand that is
    intermittent per SKU is often smooth in aggregate, and the model should see
    the smooth version when the question is asked at that level.
    """
    frame = dataset.frame

    if filters:
        for column, value in filters.items():
            if column not in frame.columns:
                raise ProductNotFoundError(
                    f"This dataset has no '{column}' column to group by.",
                    requested=column,
                    available_columns=[c for c in frame.columns if c != "date"],
                )
            frame = frame[frame[column].astype(str) == str(value)]
            if frame.empty:
                available = sorted(
                    dataset.frame[column].dropna().astype(str).unique().tolist()
                )[:10]
                raise ProductNotFoundError(
                    f"Nothing in this dataset has {column} = '{value}'.",
                    requested=value, suggestions=available,
                )

    if product_name:
        frame = frame[frame["product"] == product_name]
        if frame.empty:
            available = dataset.products()
            close = [p for p in available if product_name.lower() in p.lower()][:5]
            raise ProductNotFoundError(
                f"No rows found for product '{product_name}'.",
                requested=product_name,
                suggestions=close or available[:5],
                available_count=len(available),
            )

    if region and "region" in frame.columns:
        frame = frame[frame["region"] == region]
        if frame.empty:
            raise ProductNotFoundError(
                f"No rows found for product '{product_name}' in region '{region}'.",
                requested=product_name, region=region,
            )

    daily = frame.groupby("date")["units"].sum().sort_index()
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    series = daily.reindex(full_range, fill_value=0.0).astype(float)
    series.index.name = "date"
    return series


def assess_quality(series: pd.Series) -> DataQuality:
    """Grade a series and attach human-readable warnings.

    Thresholds are stated in configuration rather than buried here, so a reviewer
    can see exactly what "adequate" means.
    """
    settings = get_settings()
    observations = int(series.size)
    non_zero = int((series > 0).sum())
    span_days = observations  # series is reindexed gapless, so span == length
    zero_ratio = 1.0 - (non_zero / observations) if observations else 1.0
    coverage = non_zero / span_days if span_days else 0.0

    warnings: list[str] = []
    level: DataQualityLevel

    if observations < settings.min_observations:
        level = "insufficient"
    elif observations < settings.recommended_observations:
        level = "limited"
        warnings.append(
            f"Only {observations} days of history are available. "
            f"At least {settings.recommended_observations} days are recommended before "
            "weekly seasonality can be estimated reliably; treat this forecast as indicative."
        )
    elif observations < 2 * settings.recommended_observations:
        level = "adequate"
    else:
        level = "good"

    if observations < 2 * 365 and observations >= settings.recommended_observations:
        warnings.append(
            "History covers less than two years, so annual seasonality "
            "(festive peaks, end-of-season sales) cannot be separated from trend."
        )
    if zero_ratio > 0.5:
        warnings.append(
            f"{zero_ratio:.0%} of days have zero sales. Intermittent demand of this kind "
            "is better served by a count-based model (Croston, TSB) than by a continuous one."
        )
    if non_zero > 0 and float(series.max()) > float(series[series > 0].mean()) * 12:
        warnings.append(
            "The series contains an extreme outlier (a single day exceeding twelve times the "
            "mean). If this was a bulk or wholesale order rather than retail demand, "
            "consider excluding it."
        )

    return DataQuality(
        observations=observations,
        span_days=span_days,
        non_zero_days=non_zero,
        zero_day_ratio=round(zero_ratio, 4),
        coverage_ratio=round(coverage, 4),
        level=level,
        warnings=warnings,
    )


def require_forecastable(series: pd.Series, quality: DataQuality, product: str) -> None:
    """Refuse to forecast series that cannot honestly support one."""
    settings = get_settings()
    if quality.level == "insufficient":
        raise InsufficientDataError(
            f"'{product}' has only {quality.observations} days of history. "
            f"At least {settings.min_observations} are required. "
            "Rather than padding the series with synthetic history, this system declines "
            "to produce a forecast it cannot justify.",
            product=product,
            observations=quality.observations,
            required=settings.min_observations,
        )
    if quality.non_zero_days < 10:
        raise InsufficientDataError(
            f"'{product}' has sales on only {quality.non_zero_days} days. "
            "There is not enough signal to model demand.",
            product=product,
            non_zero_days=quality.non_zero_days,
        )


def weekday_profile(series: pd.Series) -> list[dict[str, float | str]]:
    """Measured mean units per weekday, with each weekday's index vs the overall mean."""
    if series.empty:
        return []
    overall = float(series.mean()) or 1.0
    grouped = series.groupby(series.index.dayofweek).mean()
    return [
        {
            "weekday": WEEKDAY_NAMES[day],
            "mean_units": round(float(value), 2),
            "index": round(float(value) / overall, 3),
        }
        for day, value in grouped.items()
    ]


def measured_weekend_uplift(series: pd.Series) -> float | None:
    """Weekend mean over weekday mean, minus one. ``None`` when not computable.

    This is *measured*, not assumed. If the data shows no weekend effect the
    number returned is near zero, and the UI reports that honestly.
    """
    if series.empty:
        return None
    is_weekend = series.index.dayofweek >= 5
    weekend, weekday = series[is_weekend], series[~is_weekend]
    if weekend.empty or weekday.empty or weekday.mean() == 0:
        return None
    return float(weekend.mean() / weekday.mean() - 1.0)


def seasonal_strength(series: pd.Series, period: int = 7) -> float:
    """Rough strength of the weekly cycle in [0, 1].

    Computed as the share of total variance explained by the day-of-week means.
    Used to decide whether a seasonal model is worth fitting at all.
    """
    if series.size < 2 * period or series.std() == 0:
        return 0.0
    dow_means = series.groupby(series.index.dayofweek).transform("mean")
    explained = float(np.var(dow_means))
    total = float(np.var(series.values))
    return round(min(1.0, explained / total), 4) if total > 0 else 0.0
