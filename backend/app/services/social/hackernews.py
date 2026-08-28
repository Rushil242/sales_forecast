"""Hacker News connector, via the public Algolia search index.

Free, unauthenticated, no quota, and it carries real engagement (points and
comment counts). Its bias is worth stating plainly: HN is a technology audience,
so it is a strong source for brand, retailer and e-commerce discussion and a weak
one for individual homeware SKUs. It is included because it is a genuinely open
source of dated, engagement-weighted discussion, not because it is representative
of retail consumers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx

from app.config import get_settings
from app.services.social import locale
from app.services.social.base import RawDocument, SocialConnector
from app.services.social.textutil import strip_html

LOG = logging.getLogger(__name__)

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNewsConnector(SocialConnector):
    name = "hackernews"
    platform = "Hacker News"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        async with httpx.AsyncClient(
            timeout=self.settings.social_request_timeout, follow_redirects=True
        ) as client:
            response = await client.get(
                SEARCH_URL,
                params={
                    # Distinctive terms only. The full product name matches
                    # nothing here, and Algolia has no region parameter -- the
                    # market cannot be applied to this source at all, which
                    # ``locale.restriction_note`` states rather than implies.
                    "query": locale.search_phrase(query, with_market=False),
                    "tags": "(story,comment)",
                    "hitsPerPage": str(min(limit, 100)),
                    "numericFilters": f"created_at_i>{int(cutoff.timestamp())}",
                },
                headers={"User-Agent": self.settings.reddit_user_agent},
            )
            response.raise_for_status()
            payload = response.json()

        documents: list[RawDocument] = []
        for hit in payload.get("hits", []):
            created = hit.get("created_at_i")
            if not created:
                continue
            published = datetime.fromtimestamp(float(created), tz=UTC)

            # A hit is either a story (title, points) or a comment (comment_text).
            title = hit.get("title") or hit.get("story_title") or ""
            body = strip_html(hit.get("comment_text") or hit.get("story_text") or "")
            if not title and not body:
                continue

            object_id = hit.get("objectID")
            documents.append(
                RawDocument(
                    source=self.platform,
                    title=(title or body[:120]).strip(),
                    text=body,
                    url=f"https://news.ycombinator.com/item?id={object_id}" if object_id else None,
                    author=hit.get("author"),
                    published_at=published,
                    engagement=float(hit.get("points") or 0)
                    + float(hit.get("num_comments") or 0) * 2.0,
                    extra={"object_id": object_id, "points": hit.get("points")},
                )
            )
            if len(documents) >= limit:
                break

        return documents
