"""Questions about what already happened.

This is the "RAG over the sales data" half of Phase 2, and it deliberately is not
vector retrieval. Retail history is a table, not a corpus: "which product is
falling fastest" has an exact answer that a groupby computes and an embedding
search only approximates. Semantic retrieval earns its place over prose --
reports, notes, reviews -- and would be a worse tool here than the arithmetic.

What it does share with RAG is the discipline: retrieve first, then answer only
from what was retrieved. Every figure below is computed from the frame and
handed to the writer as a fact; nothing is left to the model to recall.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services import datasets as dataset_registry
from app.services.agents.schemas import AgentResult, Citation, Entities
from app.services.agents.tools import call
from app.services.series import (
    build_daily_series,
    measured_weekend_uplift,
    weekday_profile,
)

NAME = "sales"

# Recent-vs-prior comparison window when the user did not name one.
DEFAULT_WINDOW_DAYS = 30


def run(entities: Entities, message: str, dataset_id: str) -> AgentResult:
    resolved = call("resolve_dataset", dataset_registry.resolve, identifier=dataset_id)
    if not resolved.ok:
        return AgentResult(
            tools=[resolved.record],
            refusal=f"I could not open the dataset '{dataset_id}'.",
        )
    dataset = resolved.value
    window = entities.lookback_days or DEFAULT_WINDOW_DAYS

    if entities.product:
        return _one_product(dataset, dataset_id, entities, window, resolved.record)
    return _across_products(dataset, dataset_id, window, resolved.record)


def _one_product(
    dataset: Any, dataset_id: str, entities: Entities, window: int, resolved_record: Any
) -> AgentResult:
    product = entities.product
    series_run = call(
        "query_sales", build_daily_series, dataset=dataset, product_name=product
    )
    if not series_run.ok:
        return AgentResult(
            tools=[resolved_record, series_run.record],
            refusal=f"There is no sales history for '{product}' in this dataset.",
        )

    series: pd.Series = series_run.value
    if series.empty:
        return AgentResult(
            tools=[resolved_record, series_run.record],
            refusal=f"'{product}' has no recorded sales in this dataset.",
        )

    recent = series.tail(window)
    prior = series.tail(window * 2).head(window)
    recent_total = float(recent.sum())
    prior_total = float(prior.sum())
    change = (
        round((recent_total - prior_total) / prior_total * 100, 1)
        if prior_total > 0 else None
    )

    facts: dict[str, Any] = {
        "product": product,
        "dataset": dataset_id,
        "product_confidence": entities.product_confidence,
        "window_days": window,
        "observations": int(series.size),
        "first_date": series.index.min().strftime("%Y-%m-%d"),
        "last_date": series.index.max().strftime("%Y-%m-%d"),
        "total_units_all_time": round(float(series.sum()), 1),
        "units_recent_window": round(recent_total, 1),
        "units_prior_window": round(prior_total, 1),
        "change_vs_prior_pct": change,
        "mean_units_per_day_recent": round(float(recent.mean()), 2),
        "best_day": {
            "date": series.idxmax().strftime("%Y-%m-%d"),
            "units": round(float(series.max()), 1),
        },
        "zero_days_in_window": int((recent == 0).sum()),
    }

    uplift = measured_weekend_uplift(series)
    if uplift is not None:
        # Measured, never assumed -- invariant 2. The sign is the whole point:
        # this dataset's real figure is negative where version 1 asserted +47%.
        facts["weekend_effect_pct"] = round(uplift, 1)
    profile = weekday_profile(series)
    if profile:
        busiest = max(profile, key=lambda row: row["mean_units"])
        facts["busiest_weekday"] = {
            "day": busiest["weekday"], "mean_units": round(float(busiest["mean_units"]), 2),
        }

    return AgentResult(
        facts=facts,
        citations=[Citation(
            label=f"Sales history for {product}",
            kind="sales",
            detail=f"{series.size} observed days, {facts['first_date']} to {facts['last_date']}",
        )],
        tools=[resolved_record, series_run.record],
        follow_ups=[
            f"Forecast {product} for the next 30 days",
            f"What are people saying about {product}?",
            "Which product is falling fastest?",
        ],
    )


def _across_products(
    dataset: Any, dataset_id: str, window: int, resolved_record: Any
) -> AgentResult:
    """Rank every product by recent movement.

    Answers "what is selling best", "what is falling fastest" and "how is the
    business doing" from one pass, because they are the same computation read
    three ways.
    """
    ranking = call("rank_products", _rank, dataset=dataset, window=window)
    if not ranking.ok:
        return AgentResult(
            tools=[resolved_record, ranking.record],
            refusal="I could not compare the products in this dataset.",
        )

    rows: list[dict[str, Any]] = ranking.value
    if not rows:
        return AgentResult(
            tools=[resolved_record, ranking.record],
            refusal="This dataset has no products with enough history to compare.",
        )

    movers = [r for r in rows if r["change_pct"] is not None]
    rising = sorted(movers, key=lambda r: r["change_pct"], reverse=True)[:5]
    falling = sorted(movers, key=lambda r: r["change_pct"])[:5]
    by_volume = sorted(rows, key=lambda r: r["units_recent"], reverse=True)[:5]

    facts: dict[str, Any] = {
        "dataset": dataset_id,
        "window_days": window,
        "products_compared": len(rows),
        "top_by_volume": by_volume,
        "rising_fastest": rising,
        "falling_fastest": falling,
        "total_units_recent": round(sum(r["units_recent"] for r in rows), 1),
        "total_units_prior": round(sum(r["units_prior"] for r in rows), 1),
    }
    prior_total = facts["total_units_prior"]
    if prior_total > 0:
        facts["overall_change_pct"] = round(
            (facts["total_units_recent"] - prior_total) / prior_total * 100, 1
        )

    return AgentResult(
        facts=facts,
        citations=[Citation(
            label=f"Sales comparison across {len(rows)} products",
            kind="sales",
            detail=f"Last {window} days against the {window} before them, from {dataset_id}",
        )],
        tools=[resolved_record, ranking.record],
        follow_ups=(
            [f"Forecast {falling[0]['product']} for the next 30 days"] if falling else []
        ) + [
            f"How did {by_volume[0]['product']} do last month?" if by_volume else "",
            "What products do I have?",
        ],
    )


def _rank(dataset: Any, window: int) -> list[dict[str, Any]]:
    """Recent versus prior units for every product, computed on the frame."""
    frame = dataset.frame
    latest = frame["date"].max()
    recent_start = latest - pd.Timedelta(days=window - 1)
    prior_start = recent_start - pd.Timedelta(days=window)

    recent = frame[frame["date"] >= recent_start]
    prior = frame[(frame["date"] >= prior_start) & (frame["date"] < recent_start)]

    recent_units = recent.groupby("product")["units"].sum()
    prior_units = prior.groupby("product")["units"].sum()

    rows: list[dict[str, Any]] = []
    for product in frame["product"].dropna().unique():
        now = float(recent_units.get(product, 0.0))
        before = float(prior_units.get(product, 0.0))
        # A product that sold nothing in either window is not a "0% change"
        # story, it is absent from the comparison entirely.
        if now == 0 and before == 0:
            continue
        rows.append({
            "product": str(product),
            "units_recent": round(now, 1),
            "units_prior": round(before, 1),
            "change_pct": round((now - before) / before * 100, 1) if before > 0 else None,
        })
    return rows
