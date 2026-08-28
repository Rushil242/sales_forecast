"""Aggregation of scored documents into platform stats, a timeline and key terms.

The one design decision worth stating up front: aggregates are **engagement
weighted**, not simple averages. A post seen by fifty thousand people is better
evidence about the market's mood than one seen by three, and treating them
equally is how a handful of low-reach outliers ends up dominating a headline
number.

Weights use ``log1p(engagement)`` rather than raw engagement, so a single viral
post shifts the index without single-handedly defining it.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from app.schemas.social import PlatformStats, SentimentPoint, TrendingTerm
from app.services.social.base import RawDocument

LOG = logging.getLogger(__name__)

# Words too common to be informative as "trending terms".
STOPWORDS = frozenset("""
a an the and or but if then than that this these those with without within from
for to of in on at by as is are was were be been being do does did have has had
it its it's i you he she they we me my your our their them his her not no yes so
just very too also more most much many any some all each other new get got make
made can could would should will shall may might must about into over under out
up down off again once here there when where why how what which who whom
""".split())

# Markup and syndication boilerplate. Belt-and-braces alongside strip_html():
# a single feed that slips through must not be able to define the trending terms.
STOPWORDS = STOPWORDS | frozenset("""
https http www com href font color target span div style class img src alt
nbsp amp quot apos rel nofollow blank text align size face table tbody
google news feed rss xml html utf via read more continue reading link
""".split())


def _weight(document: RawDocument) -> float:
    """Log-damped engagement weight, floored at 1 so zero-engagement sources count."""
    return 1.0 + math.log1p(max(0.0, document.engagement))


def weighted_sentiment(documents: list[RawDocument]) -> float:
    scored = [d for d in documents if d.sentiment_score is not None]
    if not scored:
        return 0.0
    total_weight = sum(_weight(d) for d in scored)
    if total_weight == 0:
        return 0.0
    return sum(d.sentiment_score * _weight(d) for d in scored) / total_weight


def label_for(score: float) -> str:
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"


def build_platform_stats(
    documents: list[RawDocument], lookback_days: int
) -> list[PlatformStats]:
    """Per-platform volume, engagement and sentiment, with a recent-vs-prior trend."""
    by_platform: dict[str, list[RawDocument]] = defaultdict(list)
    for document in documents:
        by_platform[document.source].append(document)

    now = datetime.now(UTC)
    midpoint = now - timedelta(days=lookback_days / 2)
    stats: list[PlatformStats] = []

    for platform, group in sorted(by_platform.items()):
        scored = [d for d in group if d.sentiment_score is not None]
        positives = sum(1 for d in scored if d.sentiment_label == "positive")
        negatives = sum(1 for d in scored if d.sentiment_label == "negative")
        engagement_total = sum(d.engagement for d in group)

        # Trend: document volume in the recent half of the window versus the prior
        # half. Only meaningful if the source actually returned documents spanning
        # the whole window. Some endpoints -- tag timelines in particular
        # -- serve only the newest N posts, so the older half looks empty purely
        # because it was never sampled. Computing a trend from that reports a
        # spurious several-hundred-percent surge, so it is suppressed instead.
        recent = sum(1 for d in group if _as_utc(d.published_at) >= midpoint)
        prior = len(group) - recent
        oldest = min(_as_utc(d.published_at) for d in group)
        window_covered = oldest < midpoint
        # Connectors flag their own truncation: hitting a result cap means older
        # documents exist that were never fetched.
        truncated = any(d.extra.get("truncated") for d in group)

        trend: float | None = None
        note = ""
        if truncated or not window_covered:
            note = (
                "Trend not reported: this source caps results and returns the newest "
                "items first, so the earlier half of the window is under-sampled and "
                "any recent-vs-prior comparison would overstate growth."
            )
        elif prior > 0:
            trend = round((recent - prior) / prior * 100, 1)

        stats.append(
            PlatformStats(
                platform=platform,
                documents=len(group),
                mentions=len(group),
                engagement_total=round(engagement_total, 1),
                engagement_rate=round(engagement_total / len(group), 2) if group else 0.0,
                sentiment_score=round(weighted_sentiment(group), 4),
                positive_share=round(positives / len(scored), 4) if scored else 0.0,
                negative_share=round(negatives / len(scored), 4) if scored else 0.0,
                trend_pct=trend,
                available=True,
                note=note,
            )
        )

    return stats


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def build_timeline(documents: list[RawDocument], lookback_days: int) -> list[SentimentPoint]:
    """Daily engagement-weighted sentiment index over the lookback window.

    Days with no documents are emitted with a sentiment index of 0.0 and a
    document count of 0. The count is what tells a reader the difference between
    "genuinely neutral" and "nothing was said", so both are always shown.
    """
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days - 1)

    buckets: dict[str, list[RawDocument]] = defaultdict(list)
    for document in documents:
        day = _as_utc(document.published_at).date()
        if start <= day <= end:
            buckets[day.isoformat()].append(document)

    timeline: list[SentimentPoint] = []
    for offset in range(lookback_days):
        day = (start + timedelta(days=offset)).isoformat()
        group = buckets.get(day, [])
        timeline.append(
            SentimentPoint(
                date=day,
                sentiment_index=round(weighted_sentiment(group), 4) if group else 0.0,
                document_count=len(group),
                mentions=len(group),
            )
        )
    return timeline


def build_trending_terms(
    documents: list[RawDocument], query: str, limit: int = 8
) -> list[TrendingTerm]:
    """Most frequent informative terms, each with the mean sentiment of its posts."""
    query_terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
    counts: Counter = Counter()
    sentiment_by_term: dict[str, list[float]] = defaultdict(list)

    for document in documents:
        tokens = {
            token for token in re.findall(r"[a-z][a-z0-9]{2,}", document.content.lower())
            if token not in STOPWORDS and token not in query_terms
        }
        for token in tokens:
            counts[token] += 1
            if document.sentiment_score is not None:
                sentiment_by_term[token].append(document.sentiment_score)

    total = sum(counts.values()) or 1
    terms: list[TrendingTerm] = []
    for term, count in counts.most_common(limit):
        scores = sentiment_by_term.get(term, [])
        mean = sum(scores) / len(scores) if scores else 0.0
        terms.append(
            TrendingTerm(
                term=term,
                count=count,
                share=round(count / total, 4),
                sentiment_score=round(mean, 4),
                sentiment_label=label_for(mean),
            )
        )
    return terms


def sentiment_index_series(documents: list[RawDocument]) -> dict[str, float]:
    """``{iso_date: index}`` over days that actually have documents.

    Fusion consumes this. Only observed days are included -- filling silent days
    with zero would tell the regression that the market felt neutral on days when
    in fact nothing was measured at all.
    """
    buckets: dict[str, list[RawDocument]] = defaultdict(list)
    for document in documents:
        buckets[_as_utc(document.published_at).date().isoformat()].append(document)
    return {day: round(weighted_sentiment(group), 6) for day, group in sorted(buckets.items())}
