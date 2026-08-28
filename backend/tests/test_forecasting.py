"""Forecaster contract, metrics and backtesting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.forecasting.backtest import plan_windows, run_backtest
from app.services.forecasting.base import CORE_QUANTILES, ForecastOutput
from app.services.forecasting.metrics import interval_coverage, mae, mape, mase, rmse, smape
from app.services.forecasting.registry import build_registry, get_forecaster
from app.services.forecasting.statistical import SeasonalNaiveForecaster

STATISTICAL = ["auto-arima", "auto-ets", "theta", "seasonal-naive"]


@pytest.mark.parametrize("model_name", STATISTICAL)
def test_forecaster_contract(series, model_name):
    """Every model must honour the shape, quantile and non-negativity contract."""
    forecaster = build_registry()[model_name]
    output = forecaster.predict(series, 14)

    assert len(output.index) == 14
    assert output.mean.shape == (14,)
    assert output.index[0] == series.index[-1] + pd.Timedelta(days=1)
    for quantile in CORE_QUANTILES:
        assert quantile in output.quantiles
    assert (output.mean >= 0).all(), "unit sales cannot be negative"
    assert (output.quantiles[0.1] <= output.quantiles[0.9] + 1e-9).all()


def test_quantiles_are_sorted_after_enforcement():
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    # Deliberately crossed quantiles, as independent heads can produce.
    output = ForecastOutput(
        index=index,
        mean=np.array([10.0, 10.0, 10.0]),
        quantiles={
            0.1: np.array([12.0, 5.0, 8.0]),
            0.5: np.array([10.0, 10.0, 10.0]),
            0.9: np.array([8.0, 15.0, 9.0]),
        },
    ).enforce_monotonic_quantiles()

    assert (output.quantiles[0.1] <= output.quantiles[0.5]).all()
    assert (output.quantiles[0.5] <= output.quantiles[0.9]).all()


def test_forecast_output_rejects_missing_core_quantiles():
    index = pd.date_range("2024-01-01", periods=2, freq="D")
    with pytest.raises(ValueError, match="missing required quantiles"):
        ForecastOutput(index=index, mean=np.zeros(2), quantiles={0.5: np.zeros(2)})


def test_has_95_reflects_actual_availability():
    index = pd.date_range("2024-01-01", periods=2, freq="D")
    core_only = ForecastOutput(
        index=index, mean=np.zeros(2),
        quantiles={q: np.zeros(2) for q in CORE_QUANTILES},
    )
    assert core_only.has_95 is False

    with_extended = ForecastOutput(
        index=index, mean=np.zeros(2),
        quantiles={q: np.zeros(2) for q in (*CORE_QUANTILES, 0.025, 0.975)},
    )
    assert with_extended.has_95 is True


def test_seasonal_naive_repeats_the_last_cycle():
    index = pd.date_range("2024-01-01", periods=21, freq="D")
    values = np.tile([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0], 3)
    output = SeasonalNaiveForecaster().predict(pd.Series(values, index=index), 7)
    assert output.mean == pytest.approx([1, 2, 3, 4, 5, 6, 7])


def test_intervals_widen_with_horizon(series):
    output = SeasonalNaiveForecaster().predict(series, 30)
    width = output.quantiles[0.9] - output.quantiles[0.1]
    # A random-walk interval must not be narrower at day 30 than at day 1.
    assert width[-1] >= width[0]


# ── metrics ───────────────────────────────────────────────────────────────────

def test_metrics_are_zero_for_a_perfect_forecast():
    actual = np.array([10.0, 20.0, 30.0])
    assert mae(actual, actual) == 0.0
    assert rmse(actual, actual) == 0.0
    assert mape(actual, actual) == 0.0
    assert smape(actual, actual) == 0.0


def test_mape_is_none_when_all_actuals_are_zero():
    assert mape(np.zeros(3), np.array([1.0, 2.0, 3.0])) is None


def test_smape_survives_zero_actuals():
    assert smape(np.array([0.0, 10.0]), np.array([0.0, 10.0])) == 0.0


def test_mase_below_one_beats_seasonal_naive():
    training = np.tile([10.0, 20.0], 20)
    actual = np.array([10.0, 20.0, 10.0, 20.0])
    good = mase(actual, actual, training)
    poor = mase(actual, np.full(4, 100.0), training)
    assert good == 0.0
    assert poor > 1.0


def test_interval_coverage_counts_containment():
    actual = np.array([1.0, 5.0, 9.0])
    lower, upper = np.array([0.0, 0.0, 0.0]), np.array([6.0, 6.0, 6.0])
    assert interval_coverage(actual, lower, upper) == pytest.approx(2 / 3)


# ── backtesting ───────────────────────────────────────────────────────────────

def test_plan_windows_respects_minimum_training_length():
    windows = plan_windows(n_observations=400, horizon=30, requested_windows=5)
    assert windows == [370, 340, 310, 280, 250]
    # 50 observations cannot support a 30-day horizon with a 60-day training floor.
    assert plan_windows(n_observations=50, horizon=30, requested_windows=5) == []


def test_backtest_returns_none_when_series_too_short(short_series):
    result = run_backtest(short_series, [SeasonalNaiveForecaster()], horizon=30, windows=3)
    assert result is None, "must report inability to measure, not fabricate metrics"


def test_backtest_scores_every_model_on_identical_windows(series):
    forecasters = [build_registry()[name] for name in ("theta", "seasonal-naive")]
    result = run_backtest(series, forecasters, horizon=14, windows=3)

    assert result is not None
    assert result.windows == 3
    assert set(result.metrics_by_model) == {"theta", "seasonal-naive"}
    assert result.best_model in result.metrics_by_model
    for metrics in result.metrics_by_model.values():
        assert metrics.rmse >= 0
        assert 0.0 <= metrics.coverage_80 <= 1.0


def test_backtest_ranks_by_mase(series):
    forecasters = [build_registry()[name] for name in ("theta", "seasonal-naive")]
    result = run_backtest(series, forecasters, horizon=14, windows=2)
    best = result.metrics_by_model[result.best_model]
    assert all(
        best.mase <= metrics.mase
        for metrics in result.metrics_by_model.values()
        if metrics.mase is not None
    )


def test_unknown_model_is_rejected():
    from app.core.errors import ModelUnavailableError

    with pytest.raises(ModelUnavailableError):
        get_forecaster("does-not-exist")


def test_registry_always_offers_a_working_fallback():
    forecaster, _ = get_forecaster("seasonal-naive")
    assert forecaster.available
