"""Noise reduction stage.

The proposed methodology calls for "filtering methods [that] select posts from
reliable accounts and high-engagement content to remove irrelevant social media
noise". This module implements that as a sequence of explicit, individually
auditable rules. Every rejected document keeps a ``filter_reason``, so the
filtering is inspectable rather than a black box, and the API reports both the
pre- and post-filter counts.

Rules deliberately err towards keeping documents. Over-filtering a low-volume
product leaves nothing to score, which is worse than admitting some noise.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from app.services.social.base import RawDocument

LOG = logging.getLogger(__name__)

MIN_CONTENT_CHARS = 20

# Promotional and affiliate spam, which dominates unfiltered product searches and
# carries seller sentiment rather than consumer sentiment.
SPAM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(buy|shop|order)\s+now\b",
        r"\b(discount|coupon|promo)\s*code\b",
        r"\bclick\s+(here|the\s+link)\b",
        r"\baffiliate\s+link\b",
        r"\blimited\s+time\s+offer\b",
        r"\bfree\s+shipping\b.*\border\b",
        r"\bdm\s+(me|us)\s+(to|for)\s+order\b",
        r"\bwhatsapp\b.*\border\b",
        r"https?://\S+\s+https?://\S+\s+https?://\S+",  # link farms
    )
)

BOT_AUTHOR_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (r"bot$", r"^auto", r"_bot_", r"deals?$", r"promo")
)


# Words that appear in product names but say nothing about what the product is.
# "Printed A-Line Kurti" was matching Japanese posts about the LINE messenger,
# because "line" is a query term and any-term-matches was the rule. The product
# is identified by "kurti"; "printed" and "line" identify nothing.
WEAK_TERMS = frozenset({
    # cuts, fits and generic descriptors
    "line", "fit", "slim", "regular", "oversized", "printed", "plain", "solid",
    "classic", "casual", "formal", "basic", "premium", "essential", "everyday",
    "blend", "style", "styled", "design", "designer", "new", "set", "pack",
    "piece", "size", "sizes", "small", "large", "medium", "long", "short",
    "sleeve", "sleeves", "neck", "round", "half", "full", "high", "low", "soft",
    # colours
    "black", "white", "blue", "green", "red", "pink", "grey", "gray", "brown",
    "beige", "navy", "olive", "cream", "ivory", "maroon", "yellow", "purple",
    "orange", "gold", "silver", "multicolour", "multicolor",
    # audience
    "men", "mens", "women", "womens", "kids", "unisex", "boys", "girls", "ladies",
    # materials that are also everyday English
    "cotton", "light", "heavy", "pure", "natural",
})

URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")


def _searchable(document: RawDocument) -> str:
    """Document text with URLs removed.

    URLs are where false matches live: a link ending ``/line-voom-demoted/``
    satisfies a search for "line" while the post is about something else
    entirely. Slugs are machine text, not what anybody said.
    """
    return URL_PATTERN.sub(" ", document.content.lower())


def _relevance(document: RawDocument, terms: list[str]) -> bool:
    """Require the query's *distinctive* term to appear, not merely any term.

    Any-term matching is far too loose for multi-word product names: one weak
    word carries the whole match and lets through documents about a different
    subject entirely. So the rule is:

    * if the query has a distinctive term, require one of those; otherwise
    * require at least two of its weak terms, since no single one identifies it.
    """
    if not terms:
        return True
    haystack = _searchable(document)

    strong = [term for term in terms if term not in WEAK_TERMS]
    if strong:
        return any(term in haystack for term in strong)

    matched = sum(1 for term in terms if term in haystack)
    return matched >= min(2, len(terms))


def _query_terms(query: str) -> list[str]:
    """Content words from the query, ignoring short filler tokens."""
    return [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2]


def apply_filters(
    documents: list[RawDocument],
    query: str,
    *,
    min_engagement_percentile: float = 0.0,
) -> tuple[list[RawDocument], Counter]:
    """Mark and partition documents. Returns ``(kept, rejection_reasons)``.

    ``min_engagement_percentile`` is applied per-platform, because a Reddit score
    and a news article's (absent) engagement are not on a common scale.
    """
    terms = _query_terms(query)
    reasons: Counter = Counter()
    seen_signatures: set[str] = set()

    for document in documents:
        content = document.content.strip()
        reason: str | None = None

        if len(content) < MIN_CONTENT_CHARS:
            reason = "too_short"
        elif not _relevance(document, terms):
            reason = "off_topic"
        elif any(pattern.search(content) for pattern in SPAM_PATTERNS):
            reason = "promotional"
        elif document.author and any(
            pattern.search(document.author) for pattern in BOT_AUTHOR_PATTERNS
        ):
            reason = "bot_author"
        else:
            # Crosspost and syndication dedupe: the same headline reprinted by ten
            # outlets should count once, not ten times.
            signature = re.sub(r"[^a-z0-9]", "", document.title.lower())[:80]
            if signature and signature in seen_signatures:
                reason = "duplicate"
            else:
                seen_signatures.add(signature)

        document.passed_filter = reason is None
        document.filter_reason = reason
        if reason:
            reasons[reason] += 1

    kept = [document for document in documents if document.passed_filter]

    if min_engagement_percentile > 0 and kept:
        kept = _filter_by_engagement(kept, min_engagement_percentile, reasons)

    LOG.info(
        "Noise filter: kept %d of %d documents (%s)",
        len(kept), len(documents),
        ", ".join(f"{reason}={count}" for reason, count in reasons.most_common())
        or "no rejections",
    )
    return kept, reasons


def _filter_by_engagement(
    documents: list[RawDocument], percentile: float, reasons: Counter
) -> list[RawDocument]:
    """Drop the least-engaged documents within each platform."""
    import numpy as np

    by_platform: dict[str, list[RawDocument]] = {}
    for document in documents:
        by_platform.setdefault(document.source, []).append(document)

    kept: list[RawDocument] = []
    for platform, group in by_platform.items():
        scores = np.array([d.engagement for d in group], dtype="float64")
        # A platform with no engagement metric at all (news RSS) must not be
        # filtered to nothing by a threshold that means nothing there.
        if scores.max() == 0:
            kept.extend(group)
            continue
        threshold = float(np.percentile(scores, percentile * 100))
        for document in group:
            if document.engagement >= threshold:
                kept.append(document)
            else:
                document.passed_filter = False
                document.filter_reason = "low_engagement"
                reasons["low_engagement"] += 1
        LOG.debug("Engagement filter on %s: threshold=%.1f", platform, threshold)

    return kept
