"""What data exists: datasets, connections, products, and how much history each has.

The least glamorous sub-agent and the one that most often prevents a wrong
answer. "How many will I sell?" is unanswerable until it is clear which product,
in which dataset, with how much history -- and a product graded ``insufficient``
is going to be refused by the forecaster, which is far better said here, before
the user waits twenty seconds for a refusal.
"""

from __future__ import annotations

from typing import Any

from app.services import datasets as dataset_registry
from app.services.agents.schemas import AgentResult, Citation, Entities
from app.services.agents.tools import call
from app.services.forecast_service import summarise_products

NAME = "catalogue"


def _list_all() -> list[Any]:
    return dataset_registry.list_connected() + dataset_registry.list_bundled()


def run(entities: Entities, message: str) -> AgentResult:
    listing = call("list_datasets", _list_all)
    if not listing.ok:
        return AgentResult(
            tools=[listing.record],
            refusal="The dataset registry could not be read, so I cannot say what is available.",
        )

    summaries = listing.value or []
    facts: dict[str, Any] = {
        "dataset_count": len(summaries),
        "datasets": [
            {
                "id": summary.name,
                "source": summary.source,
                "rows": summary.rows,
                "products": summary.products,
                "first_date": summary.first_date,
                "last_date": summary.last_date,
                "span_days": summary.span_days,
            }
            for summary in summaries
        ],
    }
    citations = [
        Citation(
            label=f"Dataset {summary.name}",
            kind="dataset",
            detail=f"{summary.rows:,} rows, {summary.products} products, "
                   f"{summary.first_date} to {summary.last_date}",
        )
        for summary in summaries[:4]
    ]

    # A live connection is the interesting one at a review: it is the proof the
    # tool runs on a real store rather than a bundled CSV.
    connected = [s for s in summaries if s.source == "connector"]
    if connected:
        facts["connected"] = [
            {"id": s.name, "rows": s.rows, "products": s.products, "span_days": s.span_days}
            for s in connected
        ]

    target = entities.dataset or (connected[0].name if connected else None) or (
        summaries[0].name if summaries else None
    )
    if target:
        facts["focus_dataset"] = target
        resolved = call("resolve_dataset", dataset_registry.resolve, identifier=target)
        if resolved.ok:
            products = call("list_products", summarise_products, dataset=resolved.value)
            if products.ok:
                rows = products.value or []
                facts["product_count"] = len(rows)
                facts["products"] = [
                    {
                        "name": row["product_name"],
                        "observations": row["observations"],
                        "total_units": round(float(row["total_units"]), 1),
                        "data_quality": row["data_quality"],
                    }
                    for row in sorted(
                        rows, key=lambda r: r["total_units"], reverse=True
                    )[:12]
                ]
                blocked = [r for r in rows if r["data_quality"] == "insufficient"]
                facts["forecastable_count"] = len(rows) - len(blocked)
                if blocked:
                    # Named here so the user learns it before asking for one.
                    facts["insufficient_products"] = [
                        r["product_name"] for r in blocked[:6]
                    ]
                return AgentResult(
                    facts=facts,
                    citations=citations,
                    tools=[listing.record, resolved.record, products.record],
                    follow_ups=_follow_ups(facts),
                )
            return AgentResult(
                facts=facts, citations=citations,
                tools=[listing.record, resolved.record, products.record],
            )

    return AgentResult(
        facts=facts, citations=citations, tools=[listing.record],
        follow_ups=_follow_ups(facts),
    )


def _follow_ups(facts: dict[str, Any]) -> list[str]:
    products = facts.get("products") or []
    if not products:
        return ["What datasets are connected?"]
    top = products[0]["name"]
    return [
        f"Forecast {top} for the next 30 days",
        f"What are people saying about {top}?",
        "Which product is falling fastest?",
    ]
