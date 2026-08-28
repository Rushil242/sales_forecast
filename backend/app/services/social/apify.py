"""Instagram and X, via Apify actors.

Why these two go through a third party
--------------------------------------
Instagram and X are the two platforms the original proposal named, and they are
the two this project cannot reach directly. Both put search behind a login wall,
and a login wall is not a bot-detection problem that a better fingerprint solves
-- there is simply no anonymous endpoint to call. Scraping them would mean
driving a logged-in account, which breaks their terms and puts a real account at
risk for a college demo.

Apify runs those scrapers as a managed service on its own infrastructure and
under its own terms, and its free monthly credit covers the volume this project
needs. That is the honest way to include them.

Without ``RETAILIQ_APIFY_TOKEN`` this connector reports itself unavailable and
names the environment variable, exactly like Reddit does. It never falls back to
anything invented.
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

BASE_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _first(item: dict, *keys: str) -> object:
    """Actors disagree on field names and change them between versions."""
    for key in keys:
        value = item.get(key)
        if value not in (None, "", []):
            return value
    return None


class _ApifyConnector(SocialConnector):
    """Shared plumbing for the two Apify-backed platforms."""

    actor: str = ""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def is_available(self) -> bool:
        return self.settings.has_apify

    def unavailable_reason(self) -> str:
        if not self.settings.has_apify:
            return (
                "Set RETAILIQ_APIFY_TOKEN to enable this source. Apify's free tier "
                "covers this project's volume and needs no card."
            )
        return ""

    def build_input(self, query: str, lookback_days: int, limit: int) -> dict:
        raise NotImplementedError

    def to_document(self, item: dict) -> RawDocument | None:
        raise NotImplementedError

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        if not self.settings.has_apify:
            raise PermissionError(self.unavailable_reason())

        url = BASE_URL.format(actor=self.actor)
        payload = self.build_input(query, lookback_days, min(limit, 50))

        async with httpx.AsyncClient(timeout=self.settings.apify_timeout) as client:
            response = await client.post(
                url, params={"token": self.settings.apify_token}, json=payload
            )

        if response.status_code == 401:
            raise PermissionError("Apify rejected the token. Check RETAILIQ_APIFY_TOKEN.")
        if response.status_code == 402:
            raise RuntimeError(
                "The Apify account is out of monthly credit, so this source returned "
                "nothing. It refills at the start of the billing month."
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Apify actor '{self.actor}' returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        items = response.json()
        if not isinstance(items, list):
            return []

        # The tweet actor answers an empty search with a list of {"noResults": ...}
        # sentinels rather than an empty list. Counting those as posts we failed to
        # date reported "10 items lacked a usable timestamp" for what was simply
        # "nobody tweeted about this", which sent a debugging session in entirely
        # the wrong direction.
        if items and all(
            isinstance(item, dict) and "noResults" in item for item in items
        ):
            LOG.info("%s: the search matched no posts", self.platform)
            return []

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        documents: list[RawDocument] = []
        undated = 0

        for item in items:
            if not isinstance(item, dict) or "noResults" in item:
                continue
            document = self.to_document(item)
            if document is None:
                undated += 1
                continue
            if document.published_at < cutoff:
                continue
            documents.append(document)
            if len(documents) >= limit:
                break

        if undated:
            LOG.info("%s: %d items lacked a usable timestamp and were dropped",
                     self.platform, undated)
        return documents


class InstagramConnector(_ApifyConnector):
    name = "instagram"
    platform = "Instagram"

    @property
    def actor(self) -> str:  # type: ignore[override]
        return self.settings.apify_instagram_actor

    def build_input(self, query: str, lookback_days: int, limit: int) -> dict:
        # The whole product name collapsed into one tag -- #printedalinekurti --
        # which nobody has ever posted, so this source returned zero while the
        # token was configured and working. What people actually tag is the
        # distinctive word plus a market variant: #kurti, #kurtiindia.
        tags = locale.hashtags(query)
        return {
            "hashtags": tags,
            "resultsLimit": max(limit, len(tags) * 8),
            "resultsType": "posts",
        }

    def to_document(self, item: dict) -> RawDocument | None:
        published = _parse_timestamp(_first(item, "timestamp", "takenAt", "createdAt"))
        if published is None:
            return None
        caption = strip_html(str(_first(item, "caption", "text", "description") or ""))
        if not caption:
            return None
        return RawDocument(
            source=self.platform,
            title=caption[:200],
            text=caption,
            url=str(_first(item, "url", "postUrl") or "") or None,
            author=str(_first(item, "ownerUsername", "username") or "") or None,
            published_at=published,
            engagement=(
                float(_first(item, "likesCount", "likes") or 0)
                + float(_first(item, "commentsCount", "comments") or 0) * 2.0
            ),
            extra={"actor": self.actor, "type": item.get("type")},
        )


class XConnector(_ApifyConnector):
    name = "x"
    platform = "X"

    @property
    def actor(self) -> str:  # type: ignore[override]
        return self.settings.apify_tweet_actor

    def build_input(self, query: str, lookback_days: int, limit: int) -> dict:
        since = (datetime.now(UTC) - timedelta(days=lookback_days)).date().isoformat()
        # A four-word product name matches no tweet. The distinctive terms plus
        # the market do, and the noise filter re-tightens afterwards -- harvest
        # broad, filter strict.
        terms = [locale.search_phrase(query), locale.core_term(query)]
        return {
            "searchTerms": list(dict.fromkeys(t for t in terms if t)),
            "maxItems": limit,
            "sort": "Latest",
            "start": since,
        }

    def to_document(self, item: dict) -> RawDocument | None:
        published = _parse_timestamp(_first(item, "createdAt", "created_at", "timestamp"))
        if published is None:
            return None
        text = strip_html(str(_first(item, "text", "full_text", "content") or ""))
        if not text:
            return None
        author = _first(item, "author", "user")
        handle = author.get("userName") if isinstance(author, dict) else author
        return RawDocument(
            source=self.platform,
            title=text[:200],
            text=text,
            url=str(_first(item, "url", "twitterUrl") or "") or None,
            author=str(handle or "") or None,
            published_at=published,
            # A repost carries further than a like, and a reply signals discussion.
            engagement=(
                float(_first(item, "likeCount", "favorite_count") or 0)
                + float(_first(item, "retweetCount", "retweet_count") or 0) * 2.0
                + float(_first(item, "replyCount", "reply_count") or 0) * 1.5
            ),
            extra={"actor": self.actor},
        )
