"""Questions about what the public is saying.

Wraps the existing social agent rather than reimplementing any of it, so the
assistant inherits the whole discipline already built into that pipeline: the
market scoping, the distinctive-term noise filter, the per-source status, and --
most importantly -- ``provenance``.

Provenance is the reason this sub-agent cannot be a thin passthrough. "People
love it" means something entirely different when it comes from a live harvest
than from a cached one taken six hours ago or a replayed fixture, and invariant 4
requires the answer to say which. It travels in the facts and in the citation.
"""

from __future__ import annotations

from typing import Any

from app.services.agents.schemas import AgentResult, Citation, Entities
from app.services.agents.tools import call_async

NAME = "social"

DEFAULT_LOOKBACK = 30

# Google Trends measures how many people looked, not whether they approved.
# Averaging it into a mood figure is a category error the pipeline already
# avoids; the sub-agent keeps them apart here too.
ATTENTION_PLATFORMS = {"Google Trends"}


async def run(entities: Entities, message: str, session: Any = None) -> AgentResult:
    query = entities.product
    if not query:
        return AgentResult(refusal=(
            "I need to know which product to look up. Ask me what products are "
            "available and I will list them."
        ))

    from app.services.social.agent import analyse

    lookback = entities.lookback_days or DEFAULT_LOOKBACK
    harvest = await call_async(
        "run_social_agent", analyse,
        query=query, session=session, lookback_days=lookback,
    )
    if not harvest.ok:
        return AgentResult(
            tools=[harvest.record],
            refusal=(
                f"The social harvest for '{query}' could not be completed. "
                f"{harvest.record.error or ''}".strip()
            ),
        )

    response = harvest.value
    opinion = [p for p in response.platforms if p.platform not in ATTENTION_PLATFORMS]
    attention = [p for p in response.platforms if p.platform in ATTENTION_PLATFORMS]
    working = [c for c in response.connectors if c.status == "ok"]
    failed = [c for c in response.connectors if c.status not in ("ok", "empty")]

    facts: dict[str, Any] = {
        "product": query,
        "product_confidence": entities.product_confidence,
        "lookback_days": lookback,
        # Never omitted. An answer without this is an unattributed answer.
        "provenance": response.provenance,
        "documents_analysed": response.total_documents,
        "documents_rejected_as_noise": response.filtered_documents,
        "sources_returning_data": len(working),
        "sources_tried": len(response.connectors),
        "overall_sentiment": round(response.overall_sentiment, 3),
        "overall_label": response.overall_label,
        "sentiment_model": response.sentiment_model.name,
        "by_platform": [
            {
                "platform": p.platform,
                "documents": p.documents,
                "sentiment": round(p.sentiment_score, 3),
                "positive_share": round(p.positive_share, 3),
                "negative_share": round(p.negative_share, 3),
            }
            for p in sorted(opinion, key=lambda p: p.documents, reverse=True)
        ],
        "talking_points": [
            {"term": t.term, "mentions": t.count, "sentiment": t.sentiment_label}
            for t in response.trending_terms[:6]
        ],
    }

    if attention:
        facts["attention_not_approval"] = [
            {
                "platform": p.platform,
                "readings": p.documents,
                "mean_interest_0_to_100": p.engagement_rate,
                "change_vs_earlier_pct": p.trend_pct,
                "note": "Search interest measures attention, not approval.",
            }
            for p in attention
        ]
    if failed:
        facts["sources_that_failed"] = [
            {"name": c.name, "reason": c.detail[:140]} for c in failed
        ]
    if response.top_documents:
        facts["example_posts"] = [
            {
                "platform": doc.source,
                "title": doc.title[:160],
                "mood": doc.sentiment_label,
            }
            for doc in response.top_documents[:5]
        ]

    if response.total_documents == 0:
        return AgentResult(
            facts=facts,
            tools=[harvest.record],
            refusal=(
                f"Nothing public was found about '{query}' in the last {lookback} days. "
                f"{len(working)} of {len(response.connectors)} sources answered, and "
                "none of them had anything on it. That usually means the product name "
                "is too specific to appear in public discussion, not that opinion is "
                "neutral."
            ),
            follow_ups=[f"Forecast {query} for the next 30 days"],
        )

    return AgentResult(
        facts=facts,
        citations=[Citation(
            label=f"Social harvest for {query}",
            kind="social",
            detail=(
                f"{response.total_documents} documents from {len(working)} of "
                f"{len(response.connectors)} sources, scored with "
                f"{response.sentiment_model.name}"
            ),
            provenance=response.provenance,
        )],
        tools=[harvest.record],
        follow_ups=[
            f"Forecast {query} for the next 30 days",
            f"How did {query} sell last month?",
        ],
        warnings=list(response.warnings),
    )
