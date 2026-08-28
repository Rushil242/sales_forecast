"""Sentiment fusion: calibration, the prior fallback, and bounds."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.config import get_settings
from app.services.forecasting.base import CORE_QUANTILES, ForecastOutput
from app.services.forecasting.fusion import apply_fusion, calibrate


def _forecast(index_start: pd.Timestamp, horizon: int, level: float = 100.0) -> ForecastOutput:
    index = pd.date_range(index_start, periods=horizon, freq="D")
    mean = np.full(horizon, level)
    return ForecastOutput(
        index=index, mean=mean,
        quantiles={q: mean * (0.6 + 0.4 * q * 2) for q in CORE_QUANTILES},
    )


def _correlated_history(days: int = 200, strength: float = 60.0):
    """Build a series whose local deviations genuinely track a sentiment index."""
    rng = np.random.default_rng(7)
    index = pd.date_range("2024-01-01", periods=days, freq="D")
    sentiment_values = rng.uniform(-0.8, 0.8, days)

    base = 100.0
    # Sales on day t respond to sentiment from 3 days earlier.
    values = np.full(days, base)
    for t in range(3, days):
        values[t] = base * (1 + strength / 100 * sentiment_values[t - 3]) + rng.normal(0, 1.0)

    series = pd.Series(values, index=index)
    sentiment = {
        day.strftime("%Y-%m-%d"): float(value)
        for day, value in zip(index, sentiment_values, strict=True)
    }
    return series, sentiment


def test_no_sentiment_means_no_adjustment(series):
    forecast = _forecast(series.index[-1] + pd.Timedelta(days=1), 10)
    adjusted, result = apply_fusion(forecast, series, {})

    assert result.applied is False
    assert result.mode == "unavailable"
    assert adjusted.mean == pytest.approx(forecast.mean)


def test_calibrates_when_overlap_is_sufficient():
    series, sentiment = _correlated_history()
    calibration = calibrate(series, sentiment)

    assert calibration.mode == "calibrated"
    assert calibration.overlap_days >= get_settings().fusion_min_overlap_days
    assert calibration.elasticity > 0, "a positive relationship must be recovered"
    assert calibration.r_squared > 0.05


def test_calibration_recovers_the_planted_lag():
    series, sentiment = _correlated_history(strength=80.0)
    calibration = calibrate(series, sentiment)
    # The signal was planted at a 3-day lead; allow neighbours for noise.
    assert calibration.lag_days in (2, 3, 4)


def test_falls_back_to_prior_when_overlap_is_thin(series):
    """The bundled 2011 dataset can never overlap a 2026 social harvest."""
    recent = {
        (pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=i)).strftime("%Y-%m-%d"): 0.4
        for i in range(10)
    }
    calibration = calibrate(series, recent)

    assert calibration.mode == "prior"
    assert calibration.overlap_days < get_settings().fusion_min_overlap_days
    assert calibration.elasticity == get_settings().fusion_prior_elasticity


def test_prior_mode_is_reported_honestly(series):
    recent = {
        (pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=i)).strftime("%Y-%m-%d"): 0.5
        for i in range(10)
    }
    forecast = _forecast(series.index[-1] + pd.Timedelta(days=1), 10)
    _, result = apply_fusion(forecast, series, recent)

    assert result.mode == "prior"
    assert "not a fit" in result.note
    assert "bounded prior" in result.note


def test_adjustment_is_capped(series):
    """An extreme sentiment reading must not be allowed to move the forecast arbitrarily."""
    settings = get_settings()
    extreme = {
        (pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=i)).strftime("%Y-%m-%d"): 1.0
        for i in range(10)
    }
    forecast = _forecast(series.index[-1] + pd.Timedelta(days=1), 10)

    original_elasticity = settings.fusion_prior_elasticity
    settings.fusion_prior_elasticity = 5.0  # absurd, to force the cap
    try:
        adjusted, result = apply_fusion(forecast, series, extreme)
        ratio = adjusted.mean[0] / forecast.mean[0] - 1
        assert abs(ratio) <= settings.fusion_max_adjustment + 1e-9
        assert "capped" in result.note
    finally:
        settings.fusion_prior_elasticity = original_elasticity


def test_fusion_scales_intervals_with_the_point_forecast(series):
    """Fusion shifts the expected level; it must not narrow the uncertainty band."""
    sentiment = {
        (pd.Timestamp.utcnow().normalize() - pd.Timedelta(days=i)).strftime("%Y-%m-%d"): 0.6
        for i in range(10)
    }
    forecast = _forecast(series.index[-1] + pd.Timedelta(days=1), 10)
    adjusted, result = apply_fusion(forecast, series, sentiment)

    assert result.applied
    before = forecast.quantiles[0.9] - forecast.quantiles[0.1]
    after = adjusted.quantiles[0.9] - adjusted.quantiles[0.1]
    assert (after >= before - 1e-9).all()


def test_disabled_fusion_is_a_no_op(series, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "fusion_enabled", False)
    forecast = _forecast(series.index[-1] + pd.Timedelta(days=1), 10)

    adjusted, result = apply_fusion(forecast, series, {"2024-01-01": 0.5})
    assert result.mode == "disabled"
    assert adjusted.mean == pytest.approx(forecast.mean)
