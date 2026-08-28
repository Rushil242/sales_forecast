"""Reddit connector, with three routes and a preference order.

Reddit withdrew anonymous access to its JSON endpoints in 2023. ``search.json``
answers **403** whatever user-agent you send, and so does ``old.reddit.com``,
which merely redirects to a login interstitial while still returning 200 -- a
detail worth knowing, because it makes a blocked request look successful.

So this connector tries, in order:

``oauth``    Free credentials from https://www.reddit.com/prefs/apps. Best
             quality and highest rate limit. Used whenever configured.
``browser``  Reddit's *site-wide* search, logged out, quietly ignores the query
             and serves a generic feed -- the page returns 200 and looks fine,
             which is worse than an error. Its *subreddit-restricted* search does
             work. So the relevant subreddits are discovered first (a
             ``site:reddit.com`` web search names them), and each is then searched
             in a real browser. Posts come back with genuine ISO timestamps.
``none``     Both unavailable: the connector reports why and the other sources
             carry on.

The middle route is the one that makes Reddit work without credentials. It costs
a browser launch, which is why it is only attempted when OAuth is absent.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime, timedelta

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.services.social.base import RawDocument, SocialConnector

LOG = logging.getLogger(__name__)

# Subreddit names that place a community in the Indian market.
LOCAL_SUBREDDIT = re.compile(
    r"india|indian|desi|bharat|bangalore|bengaluru|mumbai|delhi|chennai|hyderabad|"
    r"kolkata|pune|ahmedabad",
    re.IGNORECASE,
)
FALLBACK_SUBREDDITS = ("IndianFashionAddicts", "india")

PUBLIC_SEARCH_URL = "https://www.reddit.com/search.json"
OAUTH_SEARCH_URL = "https://oauth.reddit.com/search"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"


class RedditConnector(SocialConnector):
    name = "reddit"
    platform = "Reddit"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._token: str | None = None
        self._token_expiry: float = 0.0

    async def _access_token(self, client: httpx.AsyncClient) -> str | None:
        """Fetch (and cache) an OAuth token, if credentials were configured."""
        if not self.settings.has_reddit_oauth:
            return None
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        try:
            response = await client.post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self.settings.reddit_client_id, self.settings.reddit_client_secret),
                headers={"User-Agent": self.settings.reddit_user_agent},
            )
            response.raise_for_status()
            payload = response.json()
            self._token = payload["access_token"]
            self._token_expiry = time.time() + payload.get("expires_in", 3600)
            LOG.info("Reddit OAuth token acquired")
            return self._token
        except Exception as exc:
            LOG.warning("Reddit OAuth failed (%s); falling back to anonymous access", exc)
            return None

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _search(
        self, client: httpx.AsyncClient, query: str, limit: int, after: str | None
    ) -> dict:
        token = await self._access_token(client)
        headers = {"User-Agent": self.settings.reddit_user_agent}
        url = PUBLIC_SEARCH_URL
        if token:
            headers["Authorization"] = f"bearer {token}"
            url = OAUTH_SEARCH_URL

        params = {
            "q": query,
            "sort": "new",
            "limit": str(min(limit, 100)),
            "type": "link",
            "raw_json": "1",
        }
        if after:
            params["after"] = after

        response = await client.get(url, params=params, headers=headers)
        if response.status_code in (401, 403) and not token:
            # Reddit withdrew anonymous access to the JSON endpoints; this is now
            # the normal response for an unauthenticated client, not a transient
            # fault, so it is surfaced with the fix rather than retried.
            raise PermissionError(
                "Reddit refused anonymous access (HTTP "
                f"{response.status_code}). Create a free script app at "
                "https://www.reddit.com/prefs/apps and set RETAILIQ_REDDIT_CLIENT_ID "
                "and RETAILIQ_REDDIT_CLIENT_SECRET to enable this connector."
            )
        response.raise_for_status()
        return response.json()

    async def _discover_subreddits(
        self, query: str, limit: int = 3
    ) -> tuple[list[str], str]:
        """Ask the open web which subreddits actually discuss this product.

        Reddit's own subreddit search is behind the same wall, and a hard-coded
        list would only ever suit the products we thought of. A site-scoped web
        search names the communities for any query, which is what lets this
        generalise past the demo dataset.
        """
        import collections
        import re
        import urllib.parse

        from app.services.social import locale
        from app.services.social.fetchers import fetch as web_fetch
        from app.services.social.web import _decode_result_url

        search = urllib.parse.quote_plus(
            f"site:reddit.com {locale.search_phrase(query)}"
        )
        outcome = await web_fetch(
            f"https://html.duckduckgo.com/html/?q={search}"
            f"&kl={locale.duckduckgo_region()}"
        )
        if not outcome.ok:
            return [], outcome.reason

        from scrapling import Selector

        page = Selector(outcome.text)
        names: list[str] = []
        for anchor in page.css("a.result__a"):
            url = _decode_result_url(str(anchor.attrib.get("href", "")))
            match = re.search(r"reddit\.com/r/([A-Za-z0-9_]+)/", url)
            if match:
                names.append(match.group(1))
        # Communities whose own name places them in the market come first. A
        # kurti thread in r/IndianFashion is about this buyer's customers; the
        # same thread in a general fashion sub usually is not.
        ranked = collections.Counter(names).most_common()
        local = [n for n, _ in ranked if LOCAL_SUBREDDIT.search(n)]
        rest = [n for n, _ in ranked if not LOCAL_SUBREDDIT.search(n)]
        found = (local + rest)[:limit]

        # Nothing surfaced: fall back to the market's general communities rather
        # than returning silence, and say so.
        note = ""
        if not found:
            found = list(FALLBACK_SUBREDDITS)
            note = (
                "The web search named no communities, so the market's general "
                f"subreddits were searched instead: r/{', r/'.join(found)}."
            )
        return found, note

    async def _browser_search(
        self, subreddit: str, query: str, cutoff: datetime, limit: int
    ) -> list[RawDocument]:
        """Subreddit-restricted search, rendered. Site-wide search does not work."""
        import urllib.parse

        from app.services.social.fetchers import fetch as web_fetch

        url = (
            f"https://www.reddit.com/r/{subreddit}/search/"
            f"?q={urllib.parse.quote_plus(query)}&restrict_sr=1&sort=new"
        )
        outcome = await web_fetch(
            url, dynamic=True, timeout=80.0,
            wait_selector='a[data-testid="post-title-text"]',
        )
        if not outcome.ok:
            LOG.debug("Reddit r/%s render failed: %s", subreddit, outcome.reason)
            return []

        from scrapling import Selector

        page = Selector(outcome.text)
        anchors = page.css('a[data-testid="post-title-text"]')
        stamps = page.css("faceplate-timeago") or page.css("time")

        documents: list[RawDocument] = []
        for index, anchor in enumerate(anchors):
            title = anchor.get_all_text(strip=True)
            href = str(anchor.attrib.get("href", ""))
            if not title or not href:
                continue

            published = None
            if index < len(stamps):
                raw = str(stamps[index].attrib.get("ts")
                          or stamps[index].attrib.get("datetime") or "")
                published = _parse_iso(raw)
            # A post we cannot date cannot be placed on the timeline, and guessing
            # would corrupt the very trend this feeds.
            if published is None or published < cutoff:
                continue

            documents.append(RawDocument(
                source=self.platform,
                title=title[:250],
                url=f"https://www.reddit.com{href}" if href.startswith("/") else href,
                published_at=published,
                # The search grid does not expose scores, and inventing one would
                # skew the engagement weighting.
                engagement=0.0,
                extra={"subreddit": subreddit, "engine": "browser"},
            ))
            if len(documents) >= limit:
                break
        return documents

    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        """Prefer OAuth; fall back to rendering subreddit search in a browser."""
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        if self.settings.has_reddit_oauth:
            return await self._fetch_via_oauth(query, lookback_days, limit)

        subreddits, discovery_note = await self._discover_subreddits(query)
        if not subreddits:
            # Distinguish "we were throttled" from "Reddit will not let us in".
            # They call for completely different responses and conflating them
            # sends people off to create credentials they may not need.
            raise RuntimeError(
                f"Could not work out which subreddits discuss this. {discovery_note} "
                "Reddit's own anonymous search is disabled, so there is nothing to "
                "fall back to; retry shortly, or set RETAILIQ_REDDIT_CLIENT_ID and "
                "RETAILIQ_REDDIT_CLIENT_SECRET (free) to use the API directly."
            )

        # Two subreddits, searched at once. Sequentially this was a browser launch
        # each and the whole harvest waited on it.
        subreddits = subreddits[:2]
        per_sub = max(5, limit // len(subreddits))
        batches = await asyncio.gather(
            *(self._browser_search(s, query, cutoff, per_sub) for s in subreddits),
            return_exceptions=True,
        )
        documents: list[RawDocument] = []
        for batch in batches:
            if isinstance(batch, BaseException):
                LOG.debug("Reddit subreddit search failed: %s", batch)
                continue
            documents.extend(batch)

        if not documents:
            raise RuntimeError(
                "Reddit rendered but returned no posts inside the window for "
                f"r/{', r/'.join(subreddits)}. Anonymous site-wide search is "
                "disabled by Reddit; configure OAuth credentials for full coverage."
            )
        LOG.info("Reddit: %d posts from r/%s", len(documents), ", r/".join(subreddits))
        return documents[:limit]


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


    async def _fetch_via_oauth(
        self, query: str, lookback_days: int, limit: int
    ) -> list[RawDocument]:
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        documents: list[RawDocument] = []
        after: str | None = None

        async with httpx.AsyncClient(
            timeout=self.settings.social_request_timeout, follow_redirects=True
        ) as client:
            # Reddit pages at 100 items; walk until we have enough or run out.
            for _ in range(max(1, limit // 100 + 1)):
                payload = await self._search(client, query, limit, after)
                children = payload.get("data", {}).get("children", [])
                if not children:
                    break

                for child in children:
                    post = child.get("data", {})
                    created = post.get("created_utc")
                    if not created:
                        continue
                    published = datetime.fromtimestamp(float(created), tz=UTC)
                    if published < cutoff:
                        # Results are newest-first, so this is the end of the window.
                        return documents

                    documents.append(
                        RawDocument(
                            source=self.platform,
                            title=post.get("title", "").strip(),
                            text=(post.get("selftext") or "")[:2000].strip(),
                            url=f"https://www.reddit.com{post.get('permalink', '')}",
                            author=post.get("author"),
                            published_at=published,
                            # Score plus comments approximates total interaction better
                            # than upvotes alone, which ignore discussion volume.
                            engagement=float(post.get("score", 0))
                            + float(post.get("num_comments", 0)) * 2.0,
                            extra={
                                "subreddit": post.get("subreddit"),
                                "upvote_ratio": post.get("upvote_ratio"),
                                "num_comments": post.get("num_comments", 0),
                            },
                        )
                    )
                    if len(documents) >= limit:
                        return documents

                after = payload.get("data", {}).get("after")
                if not after:
                    break

        return documents
