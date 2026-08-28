"""Turn a forecast into a brief an owner can act on.

Two paths, and the response always says which ran:

``template``  Deterministic prose composed from the measured aggregates. Every
              sentence renders a number the pipeline computed, so it cannot invent
              anything. This is the default and needs no API key.
``llm``       Gemini, given the same aggregates, asked to translate rather than
              perceive. Warmer and better prioritised, but it is an interpretation
              and is labelled as one.

The payload builder is the important part of this module. It compacts a large
ForecastResponse into the handful of figures that actually matter to a shop owner,
which both keeps the prompt small and gives the guard a tight set of legitimate
numbers to check against.
"""

from __future__ import annotations

import logging

from app.schemas.forecast import ForecastResponse
from app.services.narrative import client
from app.services.narrative.schemas import (
    Action,
    BriefEnvelope,
    Driver,
    Finding,
    OwnerBrief,
)

LOG = logging.getLogger(__name__)

GROUP_LABELS = {
    "holiday": "Holidays and festivals",
    "weather": "Local weather",
    "calendar": "Day-of-week and payday patterns",
    "sentiment": "Social media sentiment",
}


def build_payload(response: ForecastResponse) -> dict:
    """Compact a forecast into the figures a brief may legitimately cite."""
    predicted = [p.predicted_units for p in response.forecast]
    upper = [p.upper_80 for p in response.forecast]
    lower = [p.lower_80 for p in response.forecast]

    total = sum(predicted)
    horizon = len(predicted)
    peak_index = max(range(horizon), key=lambda i: predicted[i]) if horizon else 0

    history_units = [h.units for h in response.history]
    trailing = history_units[-horizon:] if len(history_units) >= horizon else history_units
    baseline = sum(trailing) / len(trailing) if trailing else 0.0
    daily_mean = total / horizon if horizon else 0.0

    payload: dict = {
        "product": response.product_name,
        "horizon_days": response.horizon_days,
        "forecast": {
            "total_units": round(total, 1),
            "daily_average": round(daily_mean, 1),
            "recent_daily_average": round(baseline, 1),
            "change_vs_recent_pct": (
                round((daily_mean / baseline - 1) * 100, 1) if baseline > 0 else None
            ),
            "busiest_day": response.forecast[peak_index].date if horizon else None,
            "busiest_day_units": round(predicted[peak_index], 1) if horizon else None,
            "quiet_day_units": round(min(predicted), 1) if horizon else None,
            "safe_stock_total": round(sum(upper), 0),
            "low_end_total": round(sum(lower), 0),
        },
        "history": {
            "days_of_data": response.data_quality.observations,
            "days_with_sales_pct": round(response.data_quality.coverage_ratio * 100, 1),
            "quality": response.data_quality.level,
            "warnings": response.data_quality.warnings,
        },
        "model": {
            "name": response.model_info.name,
            "uses_external_signals": response.model_info.name == "chronos-2",
        },
    }

    if response.backtest:
        best = response.backtest.metrics_by_model.get(response.backtest.best_model)
        if best:
            payload["accuracy"] = {
                "checked_on_past_periods": response.backtest.windows,
                "typical_error_units": round(best.mae, 1),
                "beats_simple_guess": bool(best.mase is not None and best.mase < 1.0),
                "better_than_guess_pct": (
                    round((1 - best.mase) * 100, 1) if best.mase is not None else None
                ),
                "range_was_right_pct": (
                    round(best.coverage_80 * 100, 0) if best.coverage_80 is not None else None
                ),
                "improvement_over_baseline_pct": response.backtest.improvement_over_naive_pct,
            }

    covariates = response.covariates
    payload["external_signals"] = {
        "tested": covariates.available_groups,
        "used": covariates.selected_groups,
        "location": covariates.location,
        "results": [
            {
                "signal": GROUP_LABELS.get(s.group, s.group),
                "helped": s.helps,
                "accuracy_change_pct": s.delta_pct,
            }
            for s in covariates.scores
        ],
        "net_accuracy_gain_pct": covariates.improvement_pct,
    }

    weekday = response.insights.weekday_profile
    if weekday:
        best_day = max(weekday, key=lambda r: r["mean_units"])
        worst_day = min(weekday, key=lambda r: r["mean_units"])
        payload["weekly_pattern"] = {
            "busiest_weekday": best_day["weekday"],
            "busiest_weekday_units": best_day["mean_units"],
            "quietest_weekday": worst_day["weekday"],
            "quietest_weekday_units": worst_day["mean_units"],
        }

    return payload


# ── deterministic fallback ────────────────────────────────────────────────────

def build_template_brief(payload: dict) -> OwnerBrief:
    """Compose the brief from measured figures alone. Cannot hallucinate."""
    forecast = payload["forecast"]
    product = payload["product"]
    horizon = payload["horizon_days"]
    change = forecast.get("change_vs_recent_pct")

    if change is None:
        direction = "is expected to continue at its recent level"
    elif change > 5:
        direction = f"is expected to rise about {abs(change):.0f}%"
    elif change < -5:
        direction = f"is expected to fall about {abs(change):.0f}%"
    else:
        direction = "is expected to stay roughly flat"

    headline = (
        f"{product} {direction} over the next {horizon} days — "
        f"about {forecast['total_units']:,.0f} units in total."
    )

    summary = (
        f"Day to day that averages {forecast['daily_average']:,.1f} units, against "
        f"{forecast['recent_daily_average']:,.1f} recently. To be safe on stock, plan "
        f"for {forecast['safe_stock_total']:,.0f} units rather than the middle estimate."
    )

    findings: list[Finding] = []
    if forecast.get("busiest_day"):
        findings.append(Finding(
            text=f"The busiest day looks like {forecast['busiest_day']}, at around "
                 f"{forecast['busiest_day_units']:,.0f} units.",
            severity="info",
        ))

    pattern = payload.get("weekly_pattern")
    if pattern:
        findings.append(Finding(
            text=f"{pattern['busiest_weekday']} is consistently your strongest day and "
                 f"{pattern['quietest_weekday']} your weakest.",
            severity="info",
        ))

    accuracy = payload.get("accuracy")
    confidence = ""
    if accuracy:
        if accuracy["beats_simple_guess"]:
            confidence = (
                f"We checked this method against your last {accuracy['checked_on_past_periods']} "
                f"periods. It was typically off by about {accuracy['typical_error_units']:,.0f} "
                f"units a day, which is better than simply repeating last week. "
                "It is reasonable to plan against."
            )
        else:
            confidence = (
                f"Checked against your last {accuracy['checked_on_past_periods']} periods, this "
                "method was no better than repeating last week's numbers. Treat it as a "
                "sanity check rather than a plan."
            )
            findings.append(Finding(
                text="The forecast did not beat a simple rule of thumb on your past data.",
                severity="watch",
            ))
    else:
        confidence = (
            "There is not enough history to check how accurate this has been, so treat "
            "it as indicative."
        )

    for warning in payload["history"].get("warnings", [])[:1]:
        findings.append(Finding(text=warning, severity="watch"))

    drivers: list[Driver] = []
    signals = payload.get("external_signals", {})
    for result in signals.get("results", []):
        drivers.append(Driver(
            label=result["signal"],
            effect="improves the forecast" if result["helped"] else "made no difference",
            detail=(
                f"tested and kept ({result['accuracy_change_pct']:+.2f}% accuracy)"
                if result["helped"]
                else f"tested and left out ({result['accuracy_change_pct']:+.2f}%)"
            ),
        ))

    actions = [
        Action(
            text=f"Order enough to cover {forecast['safe_stock_total']:,.0f} units over the "
                 f"next {horizon} days so you are not caught short.",
            urgency="info",
        )
    ]
    if forecast.get("busiest_day"):
        actions.append(Action(
            text=f"Make sure the shelves are full before {forecast['busiest_day']}.",
            urgency="watch" if change and change > 5 else "info",
        ))
    if pattern:
        actions.append(Action(
            text=f"Schedule deliveries so stock peaks before {pattern['busiest_weekday']}.",
            urgency="info",
        ))

    return OwnerBrief(
        headline=headline, summary=summary, findings=findings,
        actions=actions, drivers=drivers, confidence_note=confidence,
    )


def build_brief(response: ForecastResponse) -> BriefEnvelope:
    """The owner-facing brief, preferring Gemini and falling back to the template."""
    payload = build_payload(response)

    envelope = client.generate_brief(payload)
    if envelope is not None and envelope.source == "llm":
        return envelope

    warnings: list[str] = []
    flags: list[str] = []
    if envelope is not None:
        # Gemini answered but the guard rejected it.
        warnings = envelope.warnings
        flags = envelope.guard_flags
    else:
        reason = client.unavailable_reason()
        if reason:
            warnings = [reason]

    return BriefEnvelope(
        brief=build_template_brief(payload),
        source="template",
        generated_ms=0,
        guard_flags=flags,
        warnings=warnings,
    )
