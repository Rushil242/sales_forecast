"""Response contracts for the social intelligence agent."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Sentiment = Literal["positive", "neutral", "negative"]


class SocialDocument(BaseModel):
    """One harvested item, kept so every aggregate number is traceable to sources."""

    id: str
    source: str
    url: str | None = None
    title: str
    text: str = ""
    author: str | None = None
    published_at: datetime
    engagement: float = 0.0
    sentiment_label: Sentiment | None = None
    sentiment_score: float | None = Field(
        default=None, description="signed polarity in [-1, 1]"
    )
    confidence: float | None = None
    passed_filter: bool = True
    filter_reason: str | None = None


class PlatformStats(BaseModel):
    platform: str
    documents: int
    mentions: int
    engagement_total: float
    engagement_rate: float
    sentiment_score: float
    positive_share: float
    negative_share: float
    trend_pct: float | None = None
    available: bool = True
    note: str = ""


class SentimentPoint(BaseModel):
    date: str
    sentiment_index: float = Field(description="engagement-weighted polarity in [-1, 1]")
    document_count: int
    mentions: int


class TrendingTerm(BaseModel):
    term: str
    count: int
    share: float
    sentiment_score: float
    sentiment_label: Sentiment


class ConnectorStatus(BaseModel):
    name: str
    status: Literal["ok", "empty", "unavailable", "error", "disabled"]
    documents: int = 0
    latency_ms: int | None = None
    detail: str = ""


class SentimentModelInfo(BaseModel):
    name: str
    kind: Literal["transformer", "lexicon"]
    detail: str = ""
    device: str | None = None


class SocialResponse(BaseModel):
    query: str
    generated_at: datetime
    lookback_days: int
    cached: bool
    cache_age_seconds: int | None = None

    # Explicit provenance: whether these numbers came from live sources, a
    # replayed fixture, or nothing at all. The UI surfaces this verbatim.
    provenance: Literal["live", "fixture", "cache", "none"]
    connectors: list[ConnectorStatus]
    sentiment_model: SentimentModelInfo

    total_documents: int
    filtered_documents: int
    total_mentions: int
    overall_sentiment: float
    overall_label: Sentiment

    platforms: list[PlatformStats]
    timeline: list[SentimentPoint]
    trending_terms: list[TrendingTerm]
    top_documents: list[SocialDocument]

    # The owner-facing brief, attached after construction by the narrative layer.
    # Optional so a failure there never costs the user their social analysis.
    brief: dict | None = None

    narrative: list[str] = Field(default_factory=list)
    narrative_source: Literal["llm", "template", "none"] = "none"
    warnings: list[str] = Field(default_factory=list)
