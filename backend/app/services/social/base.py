"""Connector interface for the social intelligence agent.

Every source -- Reddit, news RSS, Google Trends, or a replayed fixture -- produces
the same ``RawDocument`` shape, so the filtering, scoring and aggregation stages
downstream never need to know where a document came from.

Connectors are expected to fail. A rate limit, a blocked endpoint or an offline
machine is normal operating conditions for public web sources, not an exception
worth aborting the request over. Each connector therefore reports its own status
and the agent proceeds with whatever succeeded.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

LOG = logging.getLogger(__name__)


@dataclass
class RawDocument:
    """One harvested item, before filtering or sentiment scoring."""

    source: str
    title: str
    text: str = ""
    url: str | None = None
    author: str | None = None
    published_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Platform-native popularity (upvotes, comments, search interest). Normalised
    # per-platform later, since a Reddit score and a Trends index are not comparable.
    engagement: float = 0.0
    extra: dict[str, object] = field(default_factory=dict)

    # Populated by later pipeline stages.
    sentiment_label: str | None = None
    sentiment_score: float | None = None
    confidence: float | None = None
    passed_filter: bool = True
    filter_reason: str | None = None

    @property
    def id(self) -> str:
        basis = self.url or f"{self.source}:{self.title}:{self.published_at.isoformat()}"
        return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:16]

    @property
    def content(self) -> str:
        """Title and body joined, which is what the sentiment model scores."""
        return f"{self.title}. {self.text}".strip() if self.text else self.title


@dataclass
class ConnectorResult:
    name: str
    status: str  # ok | empty | unavailable | error | disabled
    documents: list[RawDocument] = field(default_factory=list)
    latency_ms: int | None = None
    detail: str = ""


class SocialConnector(ABC):
    """A source of public documents about a product."""

    name: str = "base"
    platform: str = "unknown"

    @abstractmethod
    async def fetch(self, query: str, lookback_days: int, limit: int) -> list[RawDocument]:
        """Return documents mentioning ``query`` from the last ``lookback_days``."""

    async def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""


class SignalConnector(ABC):
    """A source of a numeric daily interest series rather than text.

    Google Trends is the motivating case: it reports relative search interest per
    day, which is a genuine demand signal but carries no opinion to classify.
    Forcing it into the document interface would mean inventing a sentiment label
    for it, so it gets its own contract and is excluded from sentiment averages.
    """

    name: str = "signal"
    platform: str = "unknown"

    @abstractmethod
    async def fetch_signal(self, query: str, lookback_days: int) -> dict[str, float]:
        """Return ``{iso_date: value}`` interest readings over the window."""

    async def is_available(self) -> bool:
        return True
