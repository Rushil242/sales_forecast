"""Point and interval forecast accuracy metrics.

Definitions follow Hyndman & Koehler (2006), "Another look at measures of
forecast accuracy", which is also the source of MASE.
"""

from __future__ import annotations

import numpy as np

SEASON_LENGTH = 7


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def mape(actual: np.ndarray, predicted: np.ndarray) -> float | None:
    """Mean absolute percentage error, over non-zero actuals only.

    Returns ``None`` when every actual is zero. MAPE is undefined at zero and
    explodes near it, which is exactly the regime intermittent retail demand
    lives in -- hence MASE is reported alongside and preferred.
    """
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100)


def smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Symmetric MAPE, bounded at 200% and defined when actuals hit zero."""
    denominator = (np.abs(actual) + np.abs(predicted)) / 2
    mask = denominator != 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs(actual[mask] - predicted[mask]) / denominator[mask]) * 100)


def mase(
    actual: np.ndarray,
    predicted: np.ndarray,
    training: np.ndarray,
    season_length: int = SEASON_LENGTH,
) -> float | None:
    """Mean absolute scaled error.

    Scales MAE by the in-sample MAE of a seasonal-naive forecast, so a value
    below 1 means the model beat seasonal naive and values are comparable
    across products of wildly different volume.
    """
    if training.size <= season_length:
        return None
    scale = float(np.mean(np.abs(training[season_length:] - training[:-season_length])))
    if scale == 0:
        return None
    return float(mae(actual, predicted) / scale)


def interval_coverage(actual: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    """Share of actuals inside the interval.

    A well-calibrated 80% interval should score close to 0.80. Materially higher
    means the intervals are too wide to be useful; lower means they understate risk.
    """
    return float(np.mean((actual >= lower) & (actual <= upper)))
