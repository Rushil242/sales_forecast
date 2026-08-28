"""Blogs, reviews and forums: the long-form opinion the other sources miss.

Two stages, both open
---------------------
1. **Discover.** DuckDuckGo's HTML endpoint returns organic results with no key,
   no login and no JavaScript. It is used purely to find candidate pages.
2. **Read.** Each candidate is fetched and its own metadata is parsed --
   ``article:published_time``, Open Graph tags, JSON-LD ``datePublished``.

Why the second stage exists
---------------------------
A search result carries a title and a snippet but no date. Every other connector
in this pipeline produces dated documents, because the sentiment timeline is
built from those dates. Stamping undated results with "today" would put months-old
blog posts on this week's timeline and quietly corrupt the trend, so instead the
real page is read and **anything whose publication date cannot be established is
discarded rather than guessed**. That is why this connector returns fewer
documents than it discovers, and the count of both is reported.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, quote_plus, urlsplit

from app.config import get_settings
from app.services.social import locale
from app.services.social.base import RawDocument, SocialConnector
from app.services.social.fetchers import fetch, scrapling_available
from app.services.social.textutil import strip_html

LOG = logging.getLogger(__name__)

SEARCH_URL = "https://html.duckduckgo.com/html/?q={query}&kl={region}"

# Sites already covered by a dedicated connector, or that are not opinion at all.
SKIP_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "reddit.com", "www.reddit.com", "old.reddit.com",
    "news.ycombinator.com", "twitter.com", "x.com",
    "amazon.com", "www.amazon.com", "amazon.in", "www.amazon.in",
    "pinterest.com", "www.pinterest.com",
}

_JSON_LD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.I
)
_META_DATE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']'
    r'(?:article:published_time|datePublished|og:published_time|pubdate|date)["\']'
    r'[^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE
)
_OG_DESC = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\']'
    r'[^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _parse_date(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text[:20].strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _published_from_html(html: str) -> datetime | None:
    """The page's own claim about when it was published, or nothing."""
    match = _META_DATE.search(html)
    if match:
        parsed = _parse_date(match.group(1))
        if parsed:
            return parsed

    for block in _JSON_LD.findall(html)[:4]:
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph")
            if isinstance(graph, list):
                candidates.extend(item for item in graph if isinstance(item, dict))
            for key in ("datePublished", "dateCreated", "uploadDate"):
                parsed = _parse_date(str(candidate.get(key) or ""))
                if parsed:
                    return parsed
    return None


def _decode_result_url(href: str) -> str:
    """DuckDuckGo wraps results in a redirector; unwrap it to the real URL."""
    if href.startswith("//"):
        href = f"https:{href}"
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        query = parse_qs(urlsplit(href).query)
        target = query.get("uddg", [""])[0]
        if target:
            return target
    return href


class WebConnector(SocialConnector):
    name = "web"
    platform = "Blogs & reviews"

    # How many discovered pages to actually open. Each is a real HTTP request to
    # someone else's site, so the ceiling is deliberately low.
    MAX_PAGES = 10
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

    async def _discover(self, query: str) -> list[str]:
        # Measured: a plain "<product> review" returns eight organic results,
        # while the same query with OR operators returns two and a quoted phrase
        # returns none (DuckDuckGo answers those with a 202 and an empty page).
        # The simplest query is the one that actually works.
        search = f"{locale.search_phrase(query, with_market=False)} review"
        outcome = await fetch(
            SEARCH_URL.format(
                query=quote_plus(search), region=locale.duckduckgo_region()
            ),
            timeout=self.settings.scraping_timeout,
        )
        if not outcome.ok:
            raise RuntimeError(f"Web search unavailable: {outcome.reason}")

        from scrapling import Selector

        page = Selector(outcome.text)
        urls: list[str] = []
        seen_hosts: set[str] = set()

        for anchor in page.css("a.result__a"):
            href = anchor.attrib.get("href", "")
            url = _decode_result_url(str(href))
            if not url.startswith("http"):
                continue
            host = urlsplit(url).netloc.lower()
            if host in SKIP_HOSTS or host in seen_hosts:
                continue
            # One page per site keeps a single SEO farm from dominating the sample.
            seen_hosts.add(host)
            urls.append(url)
            if len(urls) >= self.MAX_PAGES:
                break

        if not urls:
            raise RuntimeError(
                "The web search returned no organic results, which usually means this "
                "network is being rate-limited. No pages were read."
            )
        return urls

    async def _read(self, url: str, cutoff: datetime) -> RawDocument | None:
        outcome = await fetch(url, timeout=self.settings.scraping_timeout)
        if not outcome.ok:
            LOG.debug("Web page %s not readable: %s", url, outcome.reason)
            return None

        published = _published_from_html(outcome.text)
        if published is None or published < cutoff:
            return None

        title_match = _OG_TITLE.search(outcome.text) or _TITLE.search(outcome.text)
        title = strip_html(title_match.group(1)) if title_match else url
        description_match = _OG_DESC.search(outcome.text)
        description = strip_html(description_match.group(1)) if description_match else ""

        if not title:
            return None

        return RawDocument(
            source=self.platform,
            title=title[:250],
            text=description[:1000],
            url=url,
            author=urlsplit(url).netloc,
            published_at=published,
            # Blogs publish no public engagement metric. Zero here is honest: it
            # means "not measurable", and the aggregator weights accordingly.
            engagement=0.0,
            extra={"host": urlsplit(url).netloc, "date_source": "page metadata"},
        )

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        urls = await self._discover(query)
        if not urls:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        semaphore = asyncio.Semaphore(self.CONCURRENCY)

        async def guarded(url: str) -> RawDocument | None:
            async with semaphore:
                try:
                    return await self._read(url, cutoff)
                except Exception as exc:
                    LOG.debug("Web page %s failed: %s", url, exc)
                    return None

        results = await asyncio.gather(*(guarded(url) for url in urls[:limit]))
        documents = [doc for doc in results if doc is not None]

        LOG.info(
            "Blogs & reviews: %d of %d discovered pages had a readable publication "
            "date inside the %d-day window",
            len(documents), len(urls), lookback_days,
        )
        return documents
