"""Google Trends connector.

Search interest is the closest freely-available proxy for consumer intent, and it
is the one signal here that is genuinely leading rather than coincident. It is
kept out of the sentiment aggregate on purpose: a search volume figure expresses
how much attention a product is getting, not whether opinion is favourable.

pytrends drives an unofficial endpoint that Google rate-limits aggressively and
changes without notice. Every failure mode is therefore treated as "signal
unavailable" rather than an error, and the agent continues without it.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.social.base import SignalConnector

LOG = logging.getLogger(__name__)


class TrendsConnector(SignalConnector):
    name = "trends"
    platform = "Google Trends"

    def __init__(self) -> None:
        self.settings = get_settings()

    async def is_available(self) -> bool:
        try:
            import pytrends  # noqa: F401
        except ImportError:
            return False
        return True

    def _fetch_sync(self, query: str, lookback_days: int) -> dict[str, float]:
        from pytrends.request import TrendReq

        timeframe = "now 7-d" if lookback_days <= 7 else (
            "today 1-m" if lookback_days <= 30 else "today 3-m"
        )
        geo = (self.settings.trends_geo or "").strip().upper()
        client = TrendReq(hl="en-IN" if geo == "IN" else "en-GB", tz=0, timeout=(10, 25))
        client.build_payload([query], cat=0, timeframe=timeframe, geo=geo, gprop="")
        frame = client.interest_over_time()

        if frame is None or frame.empty or query not in frame.columns:
            return {}
        if "isPartial" in frame.columns:
            frame = frame[~frame["isPartial"].astype(bool)]

        # Sub-daily timeframes return hourly buckets; collapse to daily means.
        daily = frame[query].resample("D").mean().dropna()
        return {index.strftime("%Y-%m-%d"): float(value) for index, value in daily.items()}

    async def fetch_signal(self, query: str, lookback_days: int) -> dict[str, float]:
        try:
            # pytrends is blocking; keep it off the event loop.
            return await asyncio.wait_for(
                asyncio.to_thread(self._fetch_sync, query, lookback_days),
                timeout=self.settings.social_request_timeout * 2,
            )
        except TimeoutError:
            LOG.warning("Google Trends timed out for '%s'", query)
            return {}
        except Exception as exc:
            LOG.warning("Google Trends unavailable for '%s': %s", query, exc)
            return {}
