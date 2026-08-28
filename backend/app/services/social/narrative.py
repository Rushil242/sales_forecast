"""The written "AI findings" layer.

Two implementations, and the response always says which one produced the text:

``template``  Deterministic prose composed from the computed aggregates. Every
              sentence is a rendering of a number the pipeline actually measured,
              so it cannot hallucinate. This is the default and needs no API key.
``llm``       Claude, given the same aggregates as structured JSON, asked to
              interpret them. Richer, but it is a language model reading a summary,
              so its output is labelled as interpretation rather than measurement.

Note what neither of these does: invent statistics. The old implementation
generated six "AI findings" whose numbers were seeded from a hash of the product
name. These read as analysis while being deterministic noise.
"""

from __future__ import annotations

import json
import logging

from app.config import get_settings
from app.schemas.social import PlatformStats, TrendingTerm

LOG = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a retail demand analyst. You will be given aggregated \
social-listening statistics for one product, already computed from real harvested \
documents.

Write 4-6 short findings (one sentence each, max 30 words) that a retail inventory \
manager could act on. Rules:
- Reference only numbers present in the supplied data. Never invent a statistic.
- If the evidence is thin (few documents), say so plainly instead of overstating.
- No preamble, no numbering, no markdown. Return one finding per line."""


def build_template_narrative(
    query: str,
    overall_sentiment: float,
    document_count: int,
    filtered_count: int,
    platforms: list[PlatformStats],
    terms: list[TrendingTerm],
    lookback_days: int,
) -> list[str]:
    """Deterministic findings, each a direct rendering of a measured quantity."""
    findings: list[str] = []

    if document_count == 0:
        return [
            f"No public documents mentioning '{query}' were found in the last "
            f"{lookback_days} days across the configured sources.",
            "With no social signal available, the demand forecast rests on "
            "transactional history alone.",
        ]

    mood = (
        "positive" if overall_sentiment > 0.15
        else "negative" if overall_sentiment < -0.15
        else "broadly neutral"
    )
    findings.append(
        f"Across {document_count} documents from the last {lookback_days} days, "
        f"sentiment towards '{query}' is {mood} at {overall_sentiment:+.2f} on a -1 to +1 scale."
    )

    # Signal-only platforms (Google Trends) report interest readings, not
    # documents. Including them here produced shares above 100%.
    document_platforms = [p for p in platforms if p.mentions > 0]

    if document_platforms:
        loudest = max(document_platforms, key=lambda p: p.documents)
        findings.append(
            f"{loudest.platform} accounts for {loudest.documents} of {document_count} "
            f"documents ({loudest.documents / document_count:.0%}), with sentiment "
            f"of {loudest.sentiment_score:+.2f} there."
        )

        rising = [p for p in document_platforms if p.trend_pct is not None and p.trend_pct > 25]
        if rising:
            top = max(rising, key=lambda p: p.trend_pct or 0)
            findings.append(
                f"Mention volume on {top.platform} is up {top.trend_pct:.0f}% in the "
                f"recent half of the window versus the prior half."
            )

        negative = [
            p for p in document_platforms if p.sentiment_score < -0.15 and p.documents >= 3
        ]
        if negative:
            worst = min(negative, key=lambda p: p.sentiment_score)
            findings.append(
                f"Sentiment on {worst.platform} is negative at {worst.sentiment_score:+.2f} "
                f"across {worst.documents} documents - worth reading before a restock decision."
            )

    if terms:
        leaders = ", ".join(f"'{t.term}'" for t in terms[:3])
        findings.append(f"The most frequent co-occurring terms are {leaders}.")

    if document_count < 15:
        findings.append(
            f"Evidence is thin: only {document_count} documents passed filtering "
            f"(from {filtered_count} harvested). Treat this signal as weak."
        )

    return findings


async def build_llm_narrative(
    query: str,
    payload: dict,
) -> list[str] | None:
    """Ask Claude to interpret the aggregates. Returns ``None`` if unavailable."""
    settings = get_settings()
    if not settings.has_llm:
        return None

    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        LOG.info("anthropic package not installed; using template narrative")
        return None

    try:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"Product: {query}\n\n"
                    f"Aggregated social statistics:\n{json.dumps(payload, indent=2, default=str)}"
                ),
            }],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        findings = [line.strip(" -*•") for line in text.splitlines() if line.strip()]
        return findings[:6] or None
    except Exception as exc:
        LOG.warning("LLM narrative failed (%s); using template narrative", exc)
        return None
