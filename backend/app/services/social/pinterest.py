"""Pinterest: reachable, but only through a real browser.

What is actually blocked, measured
----------------------------------
Pinterest's search grid is filled by an XHR to
``/resource/BaseSearchResource/get/``. Called directly it answers **403 Invalid
Resource Request**, and it does so even when the request carries the
``csrftoken`` and ``_pinterest_sess`` cookies fetched from the search page a
moment earlier plus the ``X-CSRFToken`` and ``X-Requested-With`` headers the
site's own JavaScript sends. No amount of header forgery gets past it.

What does work is letting the page make that request itself. A real browser
renders the search, Pinterest's front end calls its own endpoint, and we read the
response off the wire. That is the difference between impersonating a browser and
being one.

Two further wrinkles, both handled rather than hidden:

**The search payload carries no text.** It returns pin ids and images and nothing
else -- no title, no description. Text is what the sentiment model needs, so each
pin's own page is then fetched over plain HTTP (those *are* readable without a
browser) and its ``<title>`` used.

**Pins carry no usable date.** Search is relevance-ranked, not chronological, and
the thin payload has no ``created_at``. Every document is therefore flagged
``date_is_unknown`` and excluded from the sentiment timeline, rather than being
stamped with today's date and quietly distorting the trend.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote

from app.config import get_settings
from app.services.social import locale
from app.services.social.base import RawDocument, SocialConnector
from app.services.social.fetchers import browser_available, fetch, scrapling_available
from app.services.social.textutil import strip_html

LOG = logging.getLogger(__name__)

SEARCH_URL = "https://www.pinterest.com/search/pins/?q={query}"
# The grid's own XHR. We never call it; we watch the page call it.
RESOURCE_PATTERN = "BaseSearchResource"

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
# Pinterest suffixes most titles with its own branding.
_SUFFIX = re.compile(r"\s*[|\-–]\s*Pinterest\s*$", re.IGNORECASE)


class PinterestConnector(SocialConnector):
    name = "pinterest"
    platform = "Pinterest"

    # Each pin costs one page fetch, so the ceiling is deliberately low.
    # Measured: one render plus twelve pin fetches ran to 104s, which overran the
    # harvest budget. Eight pins is still a usable sample and lands near 60s.
    MAX_PINS = 8
    CONCURRENCY = 3

    def __init__(self) -> None:
        self.settings = get_settings()

    async def is_available(self) -> bool:
        return self.settings.scraping_enabled and scrapling_available()

    def unavailable_reason(self) -> str:
        if not self.settings.scraping_enabled:
            return "Web scraping is disabled by configuration."
        if not scrapling_available():
            return "Scrapling is not installed."
        return ""

    async def _pin_ids(self, query: str) -> list[str]:
        """Render the search and read the ids out of the page's own XHR."""
        outcome = await fetch(
            SEARCH_URL.format(query=quote(locale.search_phrase(query))),
            dynamic=True, timeout=70.0, capture_xhr=RESOURCE_PATTERN, scroll=1,
        )
        if not outcome.ok:
            usable, reason = browser_available()
            raise RuntimeError(
                "Pinterest's search API rejects anonymous requests (HTTP 403 "
                "'Invalid Resource Request'), so the page has to be rendered. "
                + (reason if not usable else outcome.reason)
            )

        ids: list[str] = []
        for payload in outcome.captured:
            if not isinstance(payload, dict):
                continue
            block = (payload.get("resource_response") or {}).get("data") or {}
            results = block.get("results") if isinstance(block, dict) else block
            if not isinstance(results, list):
                continue
            for pin in results:
                if isinstance(pin, dict) and pin.get("id"):
                    ids.append(str(pin["id"]))

        # De-duplicate while preserving the order Pinterest ranked them in.
        seen: set[str] = set()
        ordered = [i for i in ids if not (i in seen or seen.add(i))]
        if not ordered:
            raise RuntimeError(
                "Pinterest rendered but its search response carried no pins. The "
                "grid's payload shape has probably changed."
            )
        return ordered

    async def _pin_document(self, pin_id: str) -> RawDocument | None:
        """Read one pin's own page for the text the search payload omits."""
        url = f"https://www.pinterest.com/pin/{pin_id}/"
        outcome = await fetch(url, timeout=self.settings.scraping_timeout)
        if not outcome.ok:
            return None

        match = _TITLE.search(outcome.text)
        if not match:
            return None
        title = _SUFFIX.sub("", strip_html(match.group(1))).strip()
        if not title or title.lower() in {"pinterest", "pin"}:
            return None

        return RawDocument(
            source=self.platform,
            title=title[:200],
            url=url,
            # Search is relevance-ranked and the payload has no timestamp. This is
            # the harvest time, and the flag below stops anything treating it as a
            # publication date.
            published_at=datetime.now(UTC),
            engagement=0.0,
            extra={"pin_id": pin_id, "engine": "browser", "date_is_unknown": True},
        )

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        ids = (await self._pin_ids(query))[:min(limit, self.MAX_PINS)]
        semaphore = asyncio.Semaphore(self.CONCURRENCY)

        async def guarded(pin_id: str) -> RawDocument | None:
            async with semaphore:
                try:
                    return await self._pin_document(pin_id)
                except Exception as exc:
                    LOG.debug("Pinterest pin %s failed: %s", pin_id, exc)
                    return None

        results = await asyncio.gather(*(guarded(i) for i in ids))
        documents = [d for d in results if d is not None]
        LOG.info(
            "Pinterest: %d of %d pins yielded readable text (dates unknown, so these "
            "are excluded from the timeline)", len(documents), len(ids),
        )
        return documents
