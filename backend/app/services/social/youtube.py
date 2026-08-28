"""YouTube: product discussion in the form people actually search for.

Why this source is worth having
-------------------------------
The existing connectors capture news coverage and short-form chatter. YouTube
captures something neither of them does: reviews, hauls and unboxings, which is
where consumer opinion about a physical retail product usually lives. Search
results are public and need no key or login.

How the data is obtained
------------------------
YouTube's search page ships its results as a JSON blob (``ytInitialData``) inside
the HTML rather than in the markup, so this parses that blob instead of scraping
DOM elements -- it is both more reliable and less brittle than CSS selectors.

Honest limitation: dates are relative
-------------------------------------
Search results carry "3 days ago", never a timestamp. Those are converted to
approximate dates and every document is flagged ``date_is_approximate``, because
a video labelled "2 months ago" genuinely has no known day and pretending
otherwise would be exactly the kind of invented precision this project refuses.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta

from app.config import get_settings
from app.services.social import locale
from app.services.social.base import RawDocument, SocialConnector
from app.services.social.fetchers import fetch, scrapling_available
from app.services.social.textutil import parse_count, parse_relative_time

LOG = logging.getLogger(__name__)

INITIAL_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.DOTALL)
# YouTube's opaque search-filter token for "sort by upload date".
SORT_BY_DATE = "CAI%3D"


def _text(node: object) -> str:
    """Flatten YouTube's two text shapes into a plain string."""
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return str(node["simpleText"])
    return "".join(str(run.get("text", "")) for run in node.get("runs", []) or [])


def _collect(node: object, key: str, out: list[dict]) -> None:
    """Depth-first search for every occurrence of one renderer key."""
    if isinstance(node, dict):
        found = node.get(key)
        if isinstance(found, dict):
            out.append(found)
        for value in node.values():
            _collect(value, key, out)
    elif isinstance(node, list):
        for value in node:
            _collect(value, key, out)


class YouTubeConnector(SocialConnector):
    name = "youtube"
    platform = "YouTube"

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

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        # gl/hl are honoured by the results page, so this is a real regional
        # restriction rather than a wording nudge.
        term = re.sub(r"\s+", "+", locale.search_phrase(query, with_market=False).strip())
        url = (
            f"https://www.youtube.com/results?search_query={term}"
            f"&sp={SORT_BY_DATE}&gl={locale.market_code() or 'US'}&hl=en"
        )

        outcome = await fetch(url, timeout=self.settings.scraping_timeout)
        if not outcome.ok:
            raise RuntimeError(f"YouTube search unavailable: {outcome.reason}")

        match = INITIAL_DATA.search(outcome.text)
        if not match:
            # A layout change is a real failure, not an empty result set. Saying so
            # is what stops "0 mentions" from quietly meaning "our parser broke".
            raise RuntimeError(
                "YouTube returned a page without the expected ytInitialData block. "
                "The search layout has probably changed."
            )
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Could not parse YouTube's search payload: {exc}") from exc

        renderers: list[dict] = []
        _collect(data, "videoRenderer", renderers)

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        documents: list[RawDocument] = []

        for video in renderers:
            video_id = video.get("videoId")
            title = _text(video.get("title"))
            if not video_id or not title:
                continue

            published_text = _text(video.get("publishedTimeText"))
            published = parse_relative_time(published_text)
            if published is None:
                # No date at all: a live stream or a promoted result. Undated
                # documents cannot be placed on the timeline, so they are skipped.
                continue
            if published < cutoff:
                continue

            snippets = video.get("detailedMetadataSnippets") or []
            description = _text(snippets[0].get("snippetText")) if snippets else ""

            documents.append(RawDocument(
                source=self.platform,
                title=title,
                text=description,
                url=f"https://www.youtube.com/watch?v={video_id}",
                author=_text(video.get("ownerText")) or None,
                published_at=published,
                # Views are the only public engagement number on a search card.
                engagement=parse_count(_text(video.get("viewCountText"))),
                extra={
                    "video_id": video_id,
                    "published_text": published_text,
                    # Flagged all the way through to the UI: "2 months ago" is not a date.
                    "date_is_approximate": True,
                    "duration": _text(video.get("lengthText")),
                },
            ))
            if len(documents) >= limit:
                break

        LOG.info(
            "YouTube: %d of %d results fell inside the %d-day window",
            len(documents), len(renderers), lookback_days,
        )
        return documents
