"""Resolving what the user meant, without spending an LLM call on it.

Entity extraction is the part of an agent most often handed to the model, and it
is the part least worth paying for. "How many kurtis will I sell next month" has
exactly two things in it -- a product and a horizon -- and both are recoverable
by matching against data we already hold. Doing it in Python keeps a turn at one
LLM call instead of two, and makes the assistant work at all on a day when the
free-tier quota is spent.

Product matching is scored rather than boolean, and the score travels with the
answer. A 0.55 match against a thirty-product catalogue is a guess, and the
assistant is required to say which product it assumed rather than answering
confidently about the wrong one.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from app.services.agents.schemas import Entities

LOG = logging.getLogger(__name__)

# Words that carry no product identity. Shared in spirit with the social noise
# filter's WEAK_TERMS: a word too generic to identify a document is too generic
# to identify a SKU. Kept separate because the sets genuinely differ -- "sales"
# matters to a search and never to a product name.
STOPWORDS = frozenset({
    "the", "a", "an", "my", "our", "your", "of", "for", "in", "on", "at", "to",
    "how", "many", "much", "will", "would", "should", "can", "could", "do", "does",
    "did", "is", "are", "was", "were", "be", "been", "am", "i", "we", "you", "it",
    "this", "that", "these", "those", "there", "here", "what", "which", "who",
    "when", "where", "why", "and", "or", "but", "if", "then", "than", "next",
    "last", "past", "coming", "sell", "sells", "sold", "selling", "sale", "sales",
    "demand", "forecast", "predict", "prediction", "expect", "expected", "units",
    "days", "day", "week", "weeks", "month", "months", "year", "years", "quarter",
    "about", "regarding", "tell", "me", "show", "give", "get", "need", "want",
    "please", "know", "think", "people", "saying", "say", "trend", "trending",
    "buy", "buying", "stock", "inventory", "order", "reorder", "accurate",
    "accuracy", "good", "bad", "well", "product", "products", "item", "items",
})

# "next 30 days", "next month", "over the coming quarter"
_HORIZON_NUMBER = re.compile(
    r"\b(?:next|coming|following|over the next|for the next)\s+(\d{1,3})\s*(day|week|month)s?\b",
    re.IGNORECASE,
)
_HORIZON_WORD = re.compile(
    r"\b(?:next|coming|following)\s+(day|week|fortnight|month|quarter|year)\b",
    re.IGNORECASE,
)
# A bare "30 days" / "90-day" when a forecast is clearly being asked for.
_BARE_WINDOW = re.compile(r"\b(\d{1,3})[\s-]*(day|week|month)s?\b", re.IGNORECASE)
_LOOKBACK = re.compile(
    r"\b(?:last|past|previous|recent)\s+(\d{1,3})?\s*(day|week|month)s?\b", re.IGNORECASE
)

_WORD_DAYS = {
    "day": 1, "week": 7, "fortnight": 14, "month": 30, "quarter": 90, "year": 365,
}
_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}

# The API caps a horizon at forecast_max_horizon; asking for more is a real
# request that deserves a real ceiling rather than a silent truncation.
MAX_HORIZON = 180
MAX_LOOKBACK = 90


def tokenise(text: str) -> list[str]:
    """Content words, lowercased, stopwords removed."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


def _singular(word: str) -> str:
    """Crude depluralisation. 'kurtis' -> 'kurti', 'jeans' stays 'jeans'."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and not word.endswith("ses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def score_product(message: str, product: str) -> float:
    """How confident we are that ``message`` is asking about ``product``.

    Deliberately not a single similarity metric. A shopper types "kurti"; the
    catalogue says "Printed A-Line Kurti". Sequence similarity between those two
    strings is poor (0.45) while the intent is unmistakable, so token containment
    dominates and sequence similarity only breaks ties and catches typos.
    """
    message_lower = message.lower()
    product_lower = product.lower()

    if product_lower in message_lower:
        return 1.0

    product_tokens = [_singular(t) for t in tokenise(product)]
    if not product_tokens:
        return 0.0
    message_tokens = {_singular(t) for t in tokenise(message)}
    if not message_tokens:
        return 0.0

    hits = sum(1 for token in product_tokens if token in message_tokens)
    if hits:
        # Share of the product's own identifying words that the user said. The
        # last token of a product name is the head noun ("... Kurti"), so
        # matching it is worth more than matching a modifier.
        coverage = hits / len(product_tokens)
        head_bonus = 0.25 if product_tokens[-1] in message_tokens else 0.0
        return min(0.99, 0.55 + 0.4 * coverage + head_bonus)

    # No shared token: only a typo could rescue this, so demand a high ratio.
    ratio = SequenceMatcher(None, product_lower, message_lower).ratio()
    return ratio if ratio > 0.72 else 0.0


def resolve_product(message: str, candidates: list[str]) -> tuple[str | None, float]:
    """Best-matching product and its score, or ``(None, 0.0)``."""
    best: tuple[str | None, float] = (None, 0.0)
    for candidate in candidates:
        score = score_product(message, candidate)
        if score > best[1]:
            best = (candidate, score)
    return best


def extract_horizon(message: str) -> int | None:
    """Forecast horizon in days, or ``None`` if the message did not say one."""
    match = _HORIZON_NUMBER.search(message)
    if match:
        count, unit = int(match.group(1)), match.group(2).lower()
        return min(MAX_HORIZON, max(1, count * _UNIT_DAYS[unit]))

    match = _HORIZON_WORD.search(message)
    if match:
        return min(MAX_HORIZON, _WORD_DAYS[match.group(1).lower()])

    # Only trust a bare "30 days" when nothing backward-looking is being asked.
    if not _LOOKBACK.search(message):
        match = _BARE_WINDOW.search(message)
        if match:
            count, unit = int(match.group(1)), match.group(2).lower()
            return min(MAX_HORIZON, max(1, count * _UNIT_DAYS[unit]))
    return None


def extract_lookback(message: str) -> int | None:
    """Backward-looking window in days, e.g. 'in the last two weeks'."""
    match = _LOOKBACK.search(message)
    if not match:
        return None
    count = int(match.group(1)) if match.group(1) else 1
    unit = match.group(2).lower()
    return min(MAX_LOOKBACK, max(1, count * _UNIT_DAYS[unit]))


def resolve(
    message: str,
    products: list[str],
    *,
    carried: Entities | None = None,
) -> Entities:
    """Everything recoverable from one message, falling back to the last turn.

    Carrying entities forward is what makes "and what about next month?" work.
    Anything inherited is named in ``carried_over`` so the answer can say "for
    the Printed A-Line Kurti" rather than leaving the user guessing which
    product the follow-up landed on.
    """
    product, confidence = resolve_product(message, products)
    horizon = extract_horizon(message)
    lookback = extract_lookback(message)
    carried_over: list[str] = []

    if product is None and carried and carried.product:
        product = carried.product
        confidence = carried.product_confidence
        carried_over.append("product")
    if horizon is None and carried and carried.horizon_days:
        horizon = carried.horizon_days
        carried_over.append("horizon_days")

    dataset = None
    if carried and carried.dataset:
        dataset = carried.dataset
        carried_over.append("dataset")

    return Entities(
        product=product,
        product_confidence=round(confidence, 3),
        dataset=dataset,
        horizon_days=horizon,
        lookback_days=lookback,
        filters=dict(carried.filters) if carried and carried.filters else {},
        carried_over=carried_over,
    )
