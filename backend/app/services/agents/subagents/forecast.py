"""Forward-looking questions, and questions about whether to believe the answer.

One sub-agent covers both because they run the same pipeline. "How many will I
sell?" and "how accurate is that?" differ only in which part of the same
``ForecastResponse`` the answer is drawn from, and running the forecast twice to
answer them separately would double the slowest operation in the system.

``include_brief=False`` throughout: the narrative layer's owner brief is a second
Gemini call producing prose this assistant is about to write anyway. Skipping it
halves the LLM cost of a forecast turn, which matters a great deal against a
20-request daily quota.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services import datasets as dataset_registry
from app.services.agents.schemas import AgentResult, Citation, Entities
from app.services.agents.tools import call
from app.services.forecast_service import generate_forecast

NAME = "forecast"

DEFAULT_HORIZON = 30


def run(
    entities: Entities,
    message: str,
    dataset_id: str,
    *,
    want_accuracy: bool = False,
    on_stage: Callable[[str, str], None] | None = None,
) -> AgentResult:
    if not entities.product:
        return AgentResult(refusal=(
            "I need to know which product to forecast. Ask me what products are "
            "available and I will list them."
        ))

    resolved = call("resolve_dataset", dataset_registry.resolve, identifier=dataset_id)
    if not resolved.ok:
        return AgentResult(
            tools=[resolved.record],
            refusal=f"I could not open the dataset '{dataset_id}'.",
        )

    horizon = entities.horizon_days or DEFAULT_HORIZON
    run_result = call(
        "get_forecast",
        generate_forecast,
        dataset=resolved.value,
        product_name=entities.product,
        horizon=horizon,
        run_backtest_flag=True,
        use_covariates=True,
        # The assistant writes the prose; a second LLM brief would cost a
        # request and say the same thing in a different voice.
        include_brief=False,
        session=None,
        history_limit=120,
        on_stage=on_stage,
    )

    if not run_result.ok:
        # The refusal is the product working as designed, so it is relayed in
        # the owner's language rather than presented as a failure.
        detail = run_result.record.error or ""
        if "insufficient_data" in detail:
            return AgentResult(
                tools=[resolved.record, run_result.record],
                refusal=(
                    f"'{entities.product}' does not have enough sales history to "
                    "forecast honestly. I will not pad the gap with invented days "
                    "to produce a number that looks confident."
                ),
                follow_ups=["What products do I have?"],
            )
        return AgentResult(
            tools=[resolved.record, run_result.record],
            refusal=f"I could not forecast '{entities.product}'. {detail}",
        )

    response = run_result.value
    facts = _facts_from(response, entities, want_accuracy=want_accuracy)
    citations = [Citation(
        label=f"Forecast run {response.run_id[:8]}",
        kind="forecast",
        detail=(
            f"{response.model_info.name} over {response.horizon_days} days, "
            f"fitted on {response.data_quality.observations} observed days"
        ),
    )]
    if response.backtest:
        citations.append(Citation(
            label="Rolling-origin backtest",
            kind="backtest",
            detail=(
                f"{response.backtest.windows} windows of {response.backtest.horizon} days, "
                "scored on held-out actuals"
            ),
        ))

    return AgentResult(
        facts=facts,
        citations=citations,
        tools=[resolved.record, run_result.record],
        follow_ups=[
            f"How accurate is the {entities.product} forecast?" if not want_accuracy
            else f"Forecast {entities.product} for the next 60 days",
            f"What are people saying about {entities.product}?",
            "Which product is falling fastest?",
        ],
        warnings=list(response.data_quality.warnings),
    )


def _facts_from(
    response: Any, entities: Entities, *, want_accuracy: bool
) -> dict[str, Any]:
    points = response.forecast
    total = sum(point.predicted_units for point in points)
    peak = max(points, key=lambda p: p.predicted_units) if points else None

    facts: dict[str, Any] = {
        "product": response.product_name,
        "dataset": response.dataset_name,
        "product_confidence": entities.product_confidence,
        "horizon_days": response.horizon_days,
        "model": response.model_info.name,
        "total_predicted_units": round(total, 1),
        "mean_predicted_units_per_day": round(total / len(points), 2) if points else 0.0,
        "observations_used": response.data_quality.observations,
        "history_start": response.history[0].date if response.history else None,
        "history_end": response.history[-1].date if response.history else None,
    }

    if peak is not None:
        facts["peak_day"] = {
            "date": peak.date,
            "units": round(peak.predicted_units, 1),
        }
    # The 80% band is the plannable number; 95% is null by design because the
    # model's quantile heads stop at 0.9, and null means "not known", not zero.
    upper = [p.upper_80 for p in points if p.upper_80 is not None]
    if upper:
        facts["total_upper_80"] = round(sum(upper), 1)
        facts["interval_note"] = (
            "80% band. A 95% band is not reported because the model's quantile "
            "heads are trained to 0.9 only."
        )

    # Insights are computed cards, not free numbers: carry them across verbatim
    # so the writer quotes a measured value rather than deriving its own.
    insights = response.insights
    if insights is not None and insights.cards:
        facts["insight_cards"] = [
            {"label": card.label, "value": card.value, "detail": card.detail,
             "direction": card.trend}
            for card in insights.cards
        ]
        if insights.recommendations:
            facts["recommendations"] = list(insights.recommendations)

    covariates = response.covariates
    if covariates is not None:
        selected = list(getattr(covariates, "selected_groups", []) or [])
        available = list(getattr(covariates, "available_groups", []) or [])
        facts["covariates_kept"] = selected
        facts["covariates_rejected"] = [g for g in available if g not in selected]
        # This is the headline mechanism of the whole project: signals are
        # measured on the user's own series, not attached because they exist.
        facts["covariate_note"] = (
            "Each signal was tested on this product's own history and kept only "
            "if it reduced error."
        )

    backtest = response.backtest
    # Scores are keyed by model. The one that matters is the model that actually
    # served this forecast, not whichever happened to win the leaderboard.
    metrics = (
        backtest.metrics_by_model.get(response.model_info.name)
        or backtest.metrics_by_model.get(backtest.best_model)
        if backtest is not None else None
    )
    if backtest is not None and metrics is not None:
        facts["accuracy"] = {
            "mase": round(metrics.mase, 3) if metrics.mase is not None else None,
            "rmse": round(metrics.rmse, 2) if metrics.rmse is not None else None,
            "smape": round(metrics.smape, 1) if metrics.smape is not None else None,
            "windows": backtest.windows,
            "horizon": backtest.horizon,
            "improvement_over_naive_pct": (
                round(backtest.improvement_over_naive_pct, 1)
                if backtest.improvement_over_naive_pct is not None else None
            ),
            "coverage_80": (
                round(metrics.coverage_80, 2) if metrics.coverage_80 is not None else None
            ),
        }
        facts["accuracy"]["best_model"] = backtest.best_model
        if want_accuracy:
            # Every model scored on the identical windows -- that is what makes
            # this a comparison rather than a collection of separate claims.
            facts["accuracy"]["baselines"] = sorted(
                (
                    {
                        "model": name,
                        "mase": round(score.mase, 3) if score.mase is not None else None,
                        "rmse": round(score.rmse, 2),
                    }
                    for name, score in backtest.metrics_by_model.items()
                ),
                key=lambda row: (row["mase"] is None, row["mase"]),
            )[:6]
            facts["accuracy_note"] = (
                "MASE below 1 means it beat a seasonal-naive forecast on held-out "
                "history. Every model was scored on the same rolling windows."
            )
    else:
        facts["accuracy"] = None
        facts["accuracy_note"] = (
            "No backtest was possible: the series is too short to hold out a "
            "window without degrading the forecast it is meant to test."
        )

    return facts
