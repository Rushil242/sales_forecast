"""Series construction and the no-synthetic-history guarantee.

These are the regression tests for the behaviour this rebuild set out to remove.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.errors import InsufficientDataError, ProductNotFoundError
from app.services.series import (
    assess_quality,
    build_daily_series,
    measured_weekend_uplift,
    require_forecastable,
    seasonal_strength,
    weekday_profile,
)


def test_series_is_gapless_and_zero_filled(dataset):
    series = build_daily_series(dataset, "Widget A")
    assert (series.index == pd.date_range(series.index[0], series.index[-1], freq="D")).all()
    assert not series.isna().any()
    assert series.index.is_monotonic_increasing


def test_series_length_matches_observed_span_exactly(dataset):
    """The critical invariant: no observation is invented outside the real window."""
    series = build_daily_series(dataset, "Widget A")
    raw = dataset.frame[dataset.frame["product"] == "Widget A"]
    expected = (raw["date"].max() - raw["date"].min()).days + 1
    assert len(series) == expected


def test_unknown_product_raises_with_suggestions(dataset):
    with pytest.raises(ProductNotFoundError) as excinfo:
        build_daily_series(dataset, "Widget")
    assert excinfo.value.details["suggestions"]


def test_short_series_is_refused_not_padded(short_series):
    """The old code padded 15 days up to 120 with generated values. This refuses."""
    quality = assess_quality(short_series)
    assert quality.level == "insufficient"

    with pytest.raises(InsufficientDataError) as excinfo:
        require_forecastable(short_series, quality, "Cargo Shorts")

    assert excinfo.value.details["observations"] == 15
    assert "synthetic" in excinfo.value.message


def test_limited_data_warns_but_proceeds():
    index = pd.date_range("2024-01-01", periods=60, freq="D")
    series = pd.Series(np.full(60, 10.0), index=index)

    quality = assess_quality(series)
    assert quality.level == "limited"
    assert any("recommended" in warning for warning in quality.warnings)
    require_forecastable(series, quality, "Widget")  # must not raise


def test_intermittent_demand_is_flagged():
    index = pd.date_range("2024-01-01", periods=200, freq="D")
    values = np.zeros(200)
    values[::4] = 5.0  # sales on a quarter of days
    quality = assess_quality(pd.Series(values, index=index))
    assert any("intermittent" in warning.lower() for warning in quality.warnings)


def test_weekend_uplift_is_measured_not_assumed():
    """Uplift must reflect the data, including when the effect is negative."""
    index = pd.date_range("2024-01-01", periods=140, freq="D")  # starts Monday
    # Weekdays 100, weekends 20: a strong *negative* weekend effect.
    values = np.where(index.dayofweek >= 5, 20.0, 100.0)
    uplift = measured_weekend_uplift(pd.Series(values, index=index))

    assert uplift == pytest.approx(20 / 100 - 1, abs=1e-9)
    assert uplift < 0


def test_flat_series_reports_no_weekend_effect():
    index = pd.date_range("2024-01-01", periods=140, freq="D")
    uplift = measured_weekend_uplift(pd.Series(np.full(140, 50.0), index=index))
    assert uplift == pytest.approx(0.0, abs=1e-9)


def test_weekday_profile_covers_all_days(series):
    profile = weekday_profile(series)
    assert len(profile) == 7
    assert {row["weekday"] for row in profile} == {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


def test_seasonal_strength_detects_weekly_cycle():
    index = pd.date_range("2024-01-01", periods=210, freq="D")
    seasonal = pd.Series(np.where(index.dayofweek >= 5, 10.0, 100.0), index=index)
    flat = pd.Series(np.full(210, 50.0), index=index)

    assert seasonal_strength(seasonal) > 0.5
    assert seasonal_strength(flat) == 0.0
