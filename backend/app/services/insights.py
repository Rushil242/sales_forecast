"""Derived business insights.

Every figure here is computed from the forecast and the observed history. Where a
quantity cannot be computed from the data, the card says so rather than
substituting a plausible-looking constant.

The contrast with the previous implementation matters: its "weekend uplift" card
reported the hard-coded weekly weights that had been injected into the forecast a
few lines earlier, so it was reporting its own assumption back to the user as a
finding. Here the uplift is measured from the observed series, and if the data
shows no weekend effect the card reports that.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.schemas.forecast import (
    BacktestResult,
    DataQuality,
    ForecastPoint,
    InsightCard,
    Insights,
)
from app.services.series import measured_weekend_uplift, weekday_profile

LOG = logging.getLogger(__name__)


def _trend(value: float, threshold: float = 0.02) -> str:
    if value > threshold:
        return "up"
    if value < -threshold:
        return "down"
    return "flat"


def build_insights(
    history: pd.Series,
    forecast_points: list[ForecastPoint],
    quality: DataQuality,
    backtest: BacktestResult | None,
    product_name: str,
) -> Insights:
    predicted = np.array([p.predicted_units for p in forecast_points], dtype="float64")
    upper = np.array([p.upper_80 for p in forecast_points], dtype="float64")
    dates = pd.to_datetime([p.date for p in forecast_points])
    horizon = len(forecast_points)

    forecast_mean = float(predicted.mean()) if predicted.size else 0.0
    total_units = float(predicted.sum())

    # Baseline: the trailing window of equal length, so like is compared with like
    # rather than against the whole (possibly multi-year) history.
    baseline_window = history.iloc[-horizon:] if history.size >= horizon else history
    baseline_mean = float(baseline_window.mean()) if baseline_window.size else 0.0
    delta = (forecast_mean / baseline_mean - 1.0) if baseline_mean > 0 else 0.0

    cards: list[InsightCard] = [
        InsightCard(
            key="trajectory",
            label="Demand trajectory",
            value=f"{delta:+.1%}" if baseline_mean > 0 else "n/a",
            detail=(
                f"Forecast averages {forecast_mean:,.1f} units/day against a trailing "
                f"{baseline_window.size}-day baseline of {baseline_mean:,.1f}."
                if baseline_mean > 0
                else "No non-zero baseline period is available for comparison."
            ),
            trend=_trend(delta),
        )
    ]

    if predicted.size:
        peak_index = int(np.argmax(predicted))
        peak_date = dates[peak_index]
        cards.append(
            InsightCard(
                key="peak",
                label="Peak demand window",
                value=peak_date.strftime("%d %b"),
                detail=(
                    f"Highest predicted day at {predicted[peak_index]:,.1f} units; "
                    f"the 80% upper bound that day is {upper[peak_index]:,.1f}."
                ),
                trend="up",
            )
        )

    cards.append(
        InsightCard(
            key="total",
            label="Total projected units",
            value=f"{total_units:,.0f}",
            detail=(
                f"Across the {horizon}-day horizon. The 80% upper bound totals "
                f"{upper.sum():,.0f} units, which is the level to plan safety stock against."
            ),
            trend="flat",
        )
    )

    # Weekend uplift, measured from history rather than assumed.
    uplift = measured_weekend_uplift(history)
    if uplift is None:
        cards.append(
            InsightCard(
                key="weekend",
                label="Weekend effect",
                value="n/a",
                detail="History does not contain both weekend and weekday sales, "
                       "so no weekend effect can be measured.",
                trend="flat",
            )
        )
    else:
        if abs(uplift) < 0.05:
            detail = (
                f"Weekend demand runs {uplift:+.1%} against weekdays - effectively flat. "
                "No weekend-specific replenishment is warranted."
            )
        elif uplift < 0:
            detail = (
                f"Weekend demand runs {uplift:+.1%} against weekdays, i.e. materially "
                "lower. Weight replenishment towards the working week."
            )
        else:
            detail = (
                f"Weekend demand runs {uplift:+.1%} above weekdays. "
                "Bias replenishment towards Thursday and Friday deliveries."
            )
        cards.append(
            InsightCard(
                key="weekend",
                label="Weekend effect (measured)",
                value=f"{uplift:+.0%}",
                detail=detail,
                trend=_trend(uplift, 0.05),
            )
        )

    return Insights(
        cards=cards,
        recommendations=_recommendations(
            predicted, upper, dates, history, quality, backtest, product_name, uplift
        ),
        weekday_profile=weekday_profile(history),
    )


def _recommendations(
    predicted: np.ndarray,
    upper: np.ndarray,
    dates: pd.DatetimeIndex,
    history: pd.Series,
    quality: DataQuality,
    backtest: BacktestResult | None,
    product_name: str,
    uplift: float | None,
) -> list[str]:
    """Actionable directives, each traceable to a computed quantity."""
    recommendations: list[str] = []
    if not predicted.size:
        return ["No forecast points were produced, so no recommendation can be made."]

    # Safety stock from the upper bound is the standard service-level argument:
    # planning to the mean leaves you short half the time.
    total_upper = float(upper.sum())
    total_mean = float(predicted.sum())
    recommendations.append(
        f"Stock {total_upper:,.0f} units of {product_name} to cover the 80% upper bound "
        f"over the horizon; planning only to the {total_mean:,.0f}-unit central forecast "
        "leaves roughly a one-in-ten chance of running short."
    )

    peak_index = int(np.argmax(predicted))
    lead_date = dates[peak_index] - pd.Timedelta(days=7)
    recommendations.append(
        f"Peak demand falls on {dates[peak_index]:%d %b}; place the replenishment order by "
        f"{lead_date:%d %b} to allow a one-week lead time."
    )

    if uplift is not None and abs(uplift) >= 0.05:
        direction = "weekends" if uplift > 0 else "weekdays"
        recommendations.append(
            f"Demand concentrates on {direction} ({uplift:+.0%} weekend-vs-weekday). "
            f"Schedule inbound deliveries so that stock peaks before the {direction[:-1]} run."
        )

    if backtest and backtest.metrics_by_model:
        best = backtest.metrics_by_model[backtest.best_model]
        if best.mase is not None and best.mase < 1.0:
            recommendations.append(
                f"Backtesting over {backtest.windows} rolling windows gives {backtest.best_model} "
                f"a MASE of {best.mase:.2f}, i.e. {1 - best.mase:.0%} more accurate than a "
                "seasonal-naive forecast. The forecast is fit to plan against."
            )
        else:
            recommendations.append(
                f"Backtesting gives a MASE of {best.mase:.2f} - no better than repeating last "
                "week's numbers. Use this forecast as a sanity check, not a planning input."
            )
        if best.coverage_80 is not None and best.coverage_80 < 0.65:
            recommendations.append(
                f"Historical 80% intervals only contained {best.coverage_80:.0%} of actuals, "
                "so the stated uncertainty is optimistic. Widen safety stock accordingly."
            )
    else:
        recommendations.append(
            "There is not enough history to backtest this horizon, so the forecast's "
            "accuracy is unverified. Treat it as indicative."
        )

    if quality.level in {"limited", "adequate"}:
        recommendations.append(
            f"Data quality is '{quality.level}' with {quality.observations} days of history. "
            "Revisit this forecast once more history accumulates."
        )

    return recommendations
