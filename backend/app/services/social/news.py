"""News connector, over public RSS.

Google News exposes an RSS search endpoint that needs no API key and no quota,
which makes it a reliable free source of dated, attributed documents about a
product or brand. Additional feeds can be configured through
``RETAILIQ_NEWS_FEEDS``; each entry may contain a ``{query}`` placeholder.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import httpx

from app.config import get_settings
from app.services.social.base import RawDocument, SocialConnector
from app.services.social.textutil import strip_html

LOG = logging.getLogger(__name__)


class NewsConnector(SocialConnector):
    name = "news"
    platform = "News"

    def __init__(self) -> None:
        self.settings = get_settings()

    @staticmethod
    def _parse_entry(entry, cutoff: datetime) -> RawDocument | None:
        published_struct = getattr(entry, "published_parsed", None) or getattr(
            entry, "updated_parsed", None
        )
        if not published_struct:
            return None
        published = datetime(*published_struct[:6], tzinfo=UTC)
        if published < cutoff:
            return None

        source_name = getattr(getattr(entry, "source", None), "title", None)
        # RSS summaries are HTML fragments. Left raw, their markup leaks into the
        # sentiment input and dominates the trending-term counts.
        summary = strip_html(getattr(entry, "summary", ""))[:2000]
        return RawDocument(
            source="News",
            title=strip_html(getattr(entry, "title", "")).strip(),
            text=summary,
            url=getattr(entry, "link", None),
            author=source_name,
            published_at=published,
            # RSS carries no engagement metric. Left at zero rather than guessed;
            # the aggregator treats zero-engagement sources as equally weighted.
            engagement=0.0,
            extra={"publisher": source_name},
        )

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        import feedparser

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        documents: list[RawDocument] = []

        async with httpx.AsyncClient(
            timeout=self.settings.social_request_timeout, follow_redirects=True
        ) as client:
            for template in self.settings.news_feeds:
                url = template.replace("{query}", quote_plus(query))
                try:
                    response = await client.get(
                        url, headers={"User-Agent": self.settings.reddit_user_agent}
                    )
                    response.raise_for_status()
                except Exception as exc:
                    LOG.warning("News feed %s failed: %s", url[:80], exc)
                    continue

                # feedparser is synchronous and CPU-bound; keep it off the event loop.
                parsed = await asyncio.to_thread(feedparser.parse, response.content)
                for entry in parsed.entries:
                    document = self._parse_entry(entry, cutoff)
                    if document and document.title:
                        documents.append(document)
                    if len(documents) >= limit:
                        return documents

        return documents
