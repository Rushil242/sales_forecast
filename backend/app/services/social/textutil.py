"""Text normalisation shared by the connectors.

RSS summaries and social statuses are HTML fragments. Feeding that raw into the
sentiment model and the term counter is what produced trending terms like
"href", "font" and "https" -- markup masquerading as consumer vocabulary.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta

_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_BREAKS = re.compile(r"</(p|div|br|li|h[1-6])\s*>|<br\s*/?>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_URLS = re.compile(r"https?://\S+")
_WHITESPACE = re.compile(r"\s+")


def strip_html(value: str, *, drop_urls: bool = True) -> str:
    """Convert an HTML fragment to plain text.

    URLs are removed by default: they contribute no sentiment, and their path
    segments pollute term frequency counts.
    """
    if not value:
        return ""
    text = _SCRIPT_STYLE.sub(" ", value)
    text = _BREAKS.sub(" ", text)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    if drop_urls:
        text = _URLS.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def hashtag_candidates(query: str, limit: int = 3) -> list[str]:
    """Plausible hashtags for a product query, most specific first.

    "Cargo Shorts" yields ``["cargoshorts", "cargo", "shorts"]``. Tag timelines
    need a single token, so the concatenated form is tried before the individual
    words, which are broader and noisier.
    """
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
    if not words:
        return []
    candidates = ["".join(words)] if len(words) > 1 else []
    candidates.extend(words)
    seen: set[str] = set()
    unique = [c for c in candidates if not (c in seen or seen.add(c))]
    return unique[:limit]


# Relative timestamps ("3 days ago") are what search pages show instead of dates.
_RELATIVE = re.compile(
    r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE
)
_RELATIVE_UNITS = {
    "second": 1, "minute": 60, "hour": 3600, "day": 86400,
    "week": 604800, "month": 2_592_000, "year": 31_536_000,
}


def parse_relative_time(value: str, *, now: datetime | None = None) -> datetime | None:
    """Turn "3 days ago" into a timestamp, or return None if it is not one.

    The result is deliberately approximate and callers flag it as such. A search
    page that says "2 months ago" genuinely does not know the day, and rounding
    that to an exact date would be inventing precision the source never had.
    """
    match = _RELATIVE.search(value or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    reference = now or datetime.now(UTC)
    return reference - timedelta(seconds=amount * _RELATIVE_UNITS[unit])


def parse_count(value: str) -> float:
    """Parse the count formats search pages use: '8,692 views', '1.2M', '15K'."""
    text = (value or "").strip().lower().replace(",", "")
    match = re.search(r"([\d.]+)\s*([kmb])?", text)
    if not match:
        return 0.0
    try:
        number = float(match.group(1))
    except ValueError:
        return 0.0
    return number * {"k": 1e3, "m": 1e6, "b": 1e9}.get(match.group(2) or "", 1.0)
