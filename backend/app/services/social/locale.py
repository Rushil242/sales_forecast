"""Regional and lexical shaping of the search each source is asked.

Two problems solved in one place.

**The market.** This is a tool for Indian retail, so "what are people saying"
means what people *in India* are saying. Worldwide results are not merely diluted,
they are misleading: the same garment word carries a different meaning, a
different season and a different price point elsewhere. Every source is therefore
asked a region-scoped question. Where a source has a real region parameter
(Google News ``gl``/``ceid``, DuckDuckGo ``kl``, YouTube ``gl``, Google Trends
``geo``) that parameter is used, which is a genuine restriction. Where it has
none (Pinterest, Instagram, X) the market is folded into the query or the
hashtag, which biases results rather than restricting them --
:func:`restriction_note` says which of the two a source got, so the difference is
never glossed over.

**The term.** Full product names are terrible search queries. "Printed A-Line
Kurti" as an Instagram hashtag is ``#printedalinekurti``, which nobody has ever
posted, and as an X phrase it matches nothing -- both sources returned zero for
exactly this reason while the token was configured and working. What people
actually tag and tweet is the *distinctive* word: ``#kurti``. So the query is
reduced to its distinctive terms before it is handed to a source that searches
tags or phrases.
"""

from __future__ import annotations

import re

from app.config import get_settings
from app.services.social.noise_filter import WEAK_TERMS

# Sources that can genuinely be restricted to a region by the API/site itself,
# rather than merely nudged by wording.
TRUE_REGION_PARAM = frozenset({"news", "web", "youtube", "trends", "reddit"})

# Sources with no regional dimension at all: a global index where adding the
# market to the wording would not scope the results, it would only shrink them.
# Saying so is more honest than implying a restriction that was never applied.
NO_REGION_CONCEPT = frozenset({"hackernews"})

MARKET_NAMES = {
    "IN": "India",
    "GB": "the United Kingdom",
    "US": "the United States",
}

# Hashtags an Indian fashion buyer would actually find people using.
MARKET_TAGS = {"IN": ("india", "indianfashion")}


def market_code() -> str:
    return (get_settings().trends_geo or "").strip().upper()


def market_name() -> str:
    code = market_code()
    return MARKET_NAMES.get(code, code or "all regions")


def distinctive_terms(query: str) -> list[str]:
    """The words that actually identify the product.

    Shares :data:`WEAK_TERMS` with the noise filter on purpose: the words too
    generic to *admit* a document are the same words too generic to *search* for.
    """
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    strong = [t for t in tokens if t not in WEAK_TERMS]
    return strong or tokens


def core_term(query: str) -> str:
    """The single best search word: the last distinctive one.

    Product names run modifier-first and head-noun-last -- "Printed A-Line
    Kurti", "Oversized Cotton Tee" -- so the final distinctive token is the thing
    itself rather than a description of it.
    """
    terms = distinctive_terms(query)
    return terms[-1] if terms else query.strip().lower()


def search_phrase(query: str, *, with_market: bool = True) -> str:
    """A phrase for sources that take free text and have no region parameter."""
    terms = distinctive_terms(query)
    phrase = " ".join(terms) if terms else query.strip()
    if with_market and market_code():
        return f"{phrase} {market_name()}"
    return phrase


def hashtags(query: str, *, limit: int = 3) -> list[str]:
    """Tags for Instagram, most specific first, then market-qualified.

    ``#printedalinekurti`` has no posts; ``#kurti`` and ``#kurtiindia`` do.
    """
    terms = distinctive_terms(query)
    tags: list[str] = []

    if len(terms) >= 2:
        tags.append("".join(terms))          # e.g. printedkurti
    if terms:
        tags.append(terms[-1])               # e.g. kurti
        for suffix in MARKET_TAGS.get(market_code(), ()):
            tags.append(f"{terms[-1]}{suffix}")

    seen: set[str] = set()
    unique = [t for t in tags if t and not (t in seen or seen.add(t))]
    return unique[:limit]


def duckduckgo_region() -> str:
    """DuckDuckGo's own region code, e.g. ``in-en``. Empty means no preference."""
    code = market_code()
    return f"{code.lower()}-en" if code else "wt-wt"


def restriction_note(connector_name: str) -> str:
    """How this source was scoped, in words the reader can check."""
    if not market_code():
        return ""
    where = market_name()
    if connector_name in NO_REGION_CONCEPT:
        return (
            "Not scoped by region: this source is a single global index with no "
            f"region setting, so it was searched as-is rather than for {where}."
        )
    if connector_name in TRUE_REGION_PARAM:
        return f"Restricted to {where} using the source's own region setting."
    return (
        f"{where} was added to the search wording. This source has no region "
        "setting, so results are weighted towards it rather than limited to it."
    )
