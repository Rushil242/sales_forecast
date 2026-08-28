"""The social intelligence agent.

Orchestrates the pipeline from the methodology: omni-channel collection -> noise
reduction -> sentiment analysis -> numeric conversion, then aggregation and a
written interpretation.

Connectors run concurrently and are individually fault-tolerant: a rate-limited
Reddit or an offline Trends endpoint degrades the result rather than failing the
request, and every connector's outcome is reported in the response so the user
can see what the numbers are actually based on.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import SocialSnapshot
from app.schemas.social import (
    ConnectorStatus,
    PlatformStats,
    SentimentModelInfo,
    SocialDocument,
    SocialResponse,
)
from app.services.social import fixtures, locale
from app.services.social.aggregate import (
    build_platform_stats,
    build_timeline,
    build_trending_terms,
    label_for,
    sentiment_index_series,
    weighted_sentiment,
)
from app.services.social.apify import InstagramConnector, XConnector
from app.services.social.base import ConnectorResult, RawDocument, SignalConnector, SocialConnector
from app.services.social.hackernews import HackerNewsConnector
from app.services.social.narrative import build_llm_narrative, build_template_narrative
from app.services.social.news import NewsConnector
from app.services.social.noise_filter import apply_filters
from app.services.social.pinterest import PinterestConnector
from app.services.social.reddit import RedditConnector
from app.services.social.sentiment import score_documents
from app.services.social.trends import TrendsConnector
from app.services.social.web import WebConnector
from app.services.social.youtube import YouTubeConnector

LOG = logging.getLogger(__name__)

DOCUMENT_CONNECTORS: dict[str, type[SocialConnector]] = {
    "news": NewsConnector,
    "hackernews": HackerNewsConnector,
    "reddit": RedditConnector,
    # Scrapling-backed open-web sources.
    "youtube": YouTubeConnector,
    "web": WebConnector,
    "pinterest": PinterestConnector,
    # Apify-backed, because Instagram and X have no anonymous search endpoint.
    "instagram": InstagramConnector,
    "x": XConnector,
}
SIGNAL_CONNECTORS: dict[str, type[SignalConnector]] = {
    "trends": TrendsConnector,
}


def cache_key(query: str, lookback_days: int) -> str:
    return f"{query.strip().lower()}|{lookback_days}"


async def _run_document_connector(
    connector: SocialConnector, query: str, lookback_days: int, limit: int
) -> ConnectorResult:
    started = time.perf_counter()
    budget = get_settings().social_connector_timeout
    try:
        # Browser-backed sources (Reddit, Pinterest) launch a real Chromium, which
        # is worth the wait when it works and unacceptable when it hangs. A hard
        # per-connector budget means one stuck source costs its own slot and
        # nothing else -- the harvest still returns, and says what timed out.
        documents = await asyncio.wait_for(
            connector.fetch(query, lookback_days, limit), timeout=budget
        )
    except TimeoutError:
        elapsed = int((time.perf_counter() - started) * 1000)
        LOG.warning("Connector '%s' exceeded its %.0fs budget", connector.name, budget)
        return ConnectorResult(
            name=connector.name, status="error", latency_ms=elapsed,
            detail=f"Gave up after {budget:.0f}s. This source needs a browser and it "
                   "did not finish in time; the others were unaffected.",
        )
    except Exception as exc:
        LOG.warning("Connector '%s' failed: %s", connector.name, exc)
        return ConnectorResult(
            name=connector.name,
            status="error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=str(exc)[:200],
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    # Say how this source was scoped to the market. Some sources take a real
    # region parameter and some only take the wording, and the reader is entitled
    # to know which one they got before trusting "Indian context".
    scoping = locale.restriction_note(connector.name)
    return ConnectorResult(
        name=connector.name,
        status="ok" if documents else "empty",
        documents=documents,
        latency_ms=elapsed,
        detail=f"{len(documents)} documents in {elapsed} ms."
               + (f" {scoping}" if scoping else ""),
    )


async def _harvest(
    query: str, lookback_days: int, limit: int
) -> tuple[list[RawDocument], dict[str, float], list[ConnectorStatus]]:
    """Run every enabled connector concurrently."""
    settings = get_settings()
    statuses: list[ConnectorStatus] = []
    documents: list[RawDocument] = []
    signals: dict[str, float] = {}

    document_tasks = []
    for name in settings.social_connectors:
        connector_class = DOCUMENT_CONNECTORS.get(name)
        if connector_class is None:
            continue
        connector = connector_class()
        if not await connector.is_available():
            # The connector knows why it cannot run; "dependency missing" told the
            # user nothing they could act on.
            statuses.append(ConnectorStatus(
                name=name, status="unavailable",
                detail=connector.unavailable_reason() or "dependency missing",
            ))
            continue
        # Split the document budget across the connectors actually enabled.
        enabled_document_connectors = sum(
            1 for n in settings.social_connectors if n in DOCUMENT_CONNECTORS
        )
        per_connector = max(20, limit // max(1, enabled_document_connectors))
        document_tasks.append(
            _run_document_connector(connector, query, lookback_days, per_connector)
        )

    signal_tasks = []
    signal_names = []
    for name in settings.social_connectors:
        connector_class = SIGNAL_CONNECTORS.get(name)
        if connector_class is None:
            continue
        connector = connector_class()
        if not await connector.is_available():
            statuses.append(
                ConnectorStatus(
                    name=name, status="unavailable",
                    detail="pytrends not installed (pip install '.[trends]')",
                )
            )
            continue
        signal_names.append(name)
        signal_tasks.append(connector.fetch_signal(query, lookback_days))

    results = await asyncio.gather(*document_tasks, *signal_tasks, return_exceptions=True)
    document_results = results[:len(document_tasks)]
    signal_results = results[len(document_tasks):]

    for result in document_results:
        if isinstance(result, BaseException):
            LOG.warning("Connector task raised: %s", result)
            continue
        documents.extend(result.documents)
        statuses.append(
            ConnectorStatus(
                name=result.name, status=result.status,
                documents=len(result.documents),
                latency_ms=result.latency_ms, detail=result.detail,
            )
        )

    for name, result in zip(signal_names, signal_results, strict=False):
        if isinstance(result, BaseException) or not result:
            statuses.append(
                ConnectorStatus(name=name, status="empty", detail="no interest data returned")
            )
            continue
        signals.update(result)
        statuses.append(
            ConnectorStatus(
                name=name, status="ok", documents=len(result),
                detail=f"{len(result)} daily interest readings",
            )
        )

    return documents, signals, statuses


def _balanced_top_documents(
    documents: list[RawDocument], *, limit: int
) -> list[RawDocument]:
    """Best documents per platform, interleaved rather than globally ranked.

    Ranking purely by engagement hands the whole list to whichever source is
    chattiest -- one source returned 44 of 55 items for a product and filled every
    card, so a reader could not tell that Pinterest and the blogs had found
    anything at all. Taking each platform's best in turn keeps every source that
    contributed visible, which is the honest picture of where the talk is.
    """
    by_platform: dict[str, list[RawDocument]] = {}
    for document in documents:
        by_platform.setdefault(document.source, []).append(document)
    for group in by_platform.values():
        group.sort(key=lambda d: d.engagement, reverse=True)

    # Largest contributors first, so the round-robin starts with the source that
    # actually carries the conversation.
    order = sorted(by_platform, key=lambda name: len(by_platform[name]), reverse=True)

    picked: list[RawDocument] = []
    depth = 0
    while len(picked) < limit:
        added = False
        for name in order:
            group = by_platform[name]
            if depth < len(group):
                picked.append(group[depth])
                added = True
                if len(picked) >= limit:
                    break
        if not added:
            break
        depth += 1
    return picked


def _to_schema_document(document: RawDocument) -> SocialDocument:
    return SocialDocument(
        id=document.id,
        source=document.source,
        url=document.url,
        title=document.title,
        text=document.text[:500],
        author=document.author,
        published_at=document.published_at,
        engagement=document.engagement,
        sentiment_label=document.sentiment_label,
        sentiment_score=document.sentiment_score,
        confidence=document.confidence,
        passed_filter=document.passed_filter,
        filter_reason=document.filter_reason,
    )


def _load_cached(session: Session, key: str) -> SocialSnapshot | None:
    snapshot = session.execute(
        select(SocialSnapshot).where(SocialSnapshot.cache_key == key)
    ).scalar_one_or_none()
    if snapshot and snapshot.is_fresh():
        return snapshot
    return None


def _store_cache(session: Session, key: str, query: str, lookback_days: int,
                 response: SocialResponse) -> None:
    from datetime import timedelta

    settings = get_settings()
    payload = response.model_dump(mode="json")
    existing = session.execute(
        select(SocialSnapshot).where(SocialSnapshot.cache_key == key)
    ).scalar_one_or_none()

    expires = datetime.now(UTC) + timedelta(seconds=settings.social_cache_ttl_seconds)
    if existing:
        existing.payload = payload
        existing.expires_at = expires
        existing.created_at = datetime.now(UTC)
        existing.document_count = response.total_documents
        existing.connectors_used = ",".join(c.name for c in response.connectors if c.status == "ok")
    else:
        session.add(SocialSnapshot(
            cache_key=key, query=query, lookback_days=lookback_days,
            payload=payload, expires_at=expires,
            document_count=response.total_documents,
            connectors_used=",".join(c.name for c in response.connectors if c.status == "ok"),
        ))
    session.commit()


async def analyse(
    query: str,
    session: Session | None = None,
    lookback_days: int | None = None,
    *,
    use_cache: bool = True,
    allow_fixture: bool = True,
) -> SocialResponse:
    """Run the full social intelligence pipeline for one product query."""
    settings = get_settings()
    lookback_days = lookback_days or settings.social_lookback_days
    key = cache_key(query, lookback_days)
    warnings: list[str] = []

    if not settings.social_enabled:
        return _empty_response(query, lookback_days, "disabled",
                               ["Social intelligence is disabled by configuration."])

    if use_cache and session is not None:
        cached = _load_cached(session, key)
        if cached:
            age = int((datetime.now(UTC) - _aware(cached.created_at)).total_seconds())
            LOG.info("Social cache hit for '%s' (age %ds)", query, age)
            response = SocialResponse.model_validate(cached.payload)
            response.cached = True
            response.cache_age_seconds = age
            return response

    documents, signals, statuses = await _harvest(query, lookback_days,
                                                  settings.social_max_documents)
    provenance = "live"

    if not documents and allow_fixture:
        replay = fixtures.load_fixture(query)
        if replay:
            documents, signals, recorded_at = replay
            provenance = "fixture"
            statuses.append(ConnectorStatus(
                name="fixture", status="ok", documents=len(documents),
                detail=f"replayed harvest recorded {recorded_at.date().isoformat()}",
            ))
            warnings.append(
                f"Live sources returned nothing, so a harvest recorded on "
                f"{recorded_at.date().isoformat()} is being replayed. These are real "
                "documents, but they are not current."
            )

    if not documents:
        warnings.append(
            "No documents were retrieved. This usually means the product name is too "
            "specific to appear in public discussion, or the sources are rate-limiting "
            "this network."
        )
        response = _empty_response(query, lookback_days, "none", warnings)
        response.connectors = statuses
        # An empty result is exactly where the reader most needs an explanation of
        # what was tried, so the brief is attached here too.
        try:
            from app.services.narrative.social_briefing import build_brief

            response.brief = build_brief(response).model_dump(mode="json")
        except Exception as exc:
            LOG.warning("Could not build the empty-result brief: %s", exc)
        return response

    harvested_count = len(documents)
    kept, rejections = apply_filters(documents, query)
    if not kept:
        warnings.append(
            f"All {harvested_count} harvested documents were rejected by the noise "
            f"filter ({dict(rejections)}). Reporting unfiltered results instead."
        )
        kept = documents

    model_descriptor = await score_documents(kept)

    overall = weighted_sentiment(kept)
    platforms = build_platform_stats(kept, lookback_days)
    if signals:
        platforms.append(_trends_platform(signals))

    timeline = build_timeline(kept, lookback_days)
    terms = build_trending_terms(kept, query)
    top_documents = _balanced_top_documents(kept, limit=24)

    narrative_payload = {
        "overall_sentiment": round(overall, 3),
        "documents_analysed": len(kept),
        "documents_harvested": harvested_count,
        "lookback_days": lookback_days,
        "platforms": [p.model_dump() for p in platforms],
        "trending_terms": [t.model_dump() for t in terms],
    }
    narrative = await build_llm_narrative(query, narrative_payload)
    narrative_source = "llm"
    if not narrative:
        narrative = build_template_narrative(
            query, overall, len(kept), harvested_count, platforms, terms, lookback_days
        )
        narrative_source = "template"

    if model_descriptor.kind == "lexicon":
        warnings.append(
            "The transformer sentiment model could not be loaded, so a simple keyword "
            "scorer was used. Sentiment figures are indicative only."
        )

    response = SocialResponse(
        query=query,
        generated_at=datetime.now(UTC),
        lookback_days=lookback_days,
        cached=False,
        cache_age_seconds=None,
        provenance=provenance,
        connectors=statuses,
        sentiment_model=SentimentModelInfo(
            name=model_descriptor.name, kind=model_descriptor.kind,
            detail=model_descriptor.detail, device=model_descriptor.device,
        ),
        total_documents=len(kept),
        filtered_documents=harvested_count - len(kept),
        total_mentions=len(kept),
        overall_sentiment=round(overall, 4),
        overall_label=label_for(overall),
        platforms=platforms,
        timeline=timeline,
        trending_terms=terms,
        top_documents=[_to_schema_document(d) for d in top_documents],
        narrative=narrative,
        narrative_source=narrative_source,
        warnings=warnings,
    )

    # The brief needs a finished response to summarise, so it is attached last.
    # A failure here must not cost the user their analysis.
    try:
        from app.services.narrative.social_briefing import build_brief

        response.brief = build_brief(response).model_dump(mode="json")
    except Exception as exc:
        LOG.warning("Could not build the social brief: %s", exc)

    if session is not None:
        try:
            _store_cache(session, key, query, lookback_days, response)
        except Exception as exc:
            LOG.warning("Could not cache social snapshot: %s", exc)

    return response


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _trends_region() -> str:
    """Human-readable name for the configured Trends region, for attribution."""
    geo = (get_settings().trends_geo or "").strip().upper()
    return {"IN": "India", "GB": "the United Kingdom", "US": "the United States"}.get(
        geo, geo or "all regions"
    )


def _trends_platform(signals: dict[str, float]) -> PlatformStats:
    """Represent Google Trends alongside the document platforms.

    Sentiment is fixed at 0.0 and flagged in the note: search interest measures
    attention, not approval, and averaging it into the sentiment figure would be
    a category error.
    """
    values = list(signals.values())
    mean = sum(values) / len(values) if values else 0.0
    midpoint = len(values) // 2
    trend = None
    if midpoint > 0:
        earlier = sum(values[:midpoint]) / midpoint
        later = sum(values[midpoint:]) / (len(values) - midpoint)
        if earlier > 0:
            trend = round((later - earlier) / earlier * 100, 1)

    return PlatformStats(
        platform="Google Trends",
        documents=len(values),
        mentions=0,
        engagement_total=round(sum(values), 1),
        engagement_rate=round(mean, 2),
        sentiment_score=0.0,
        positive_share=0.0,
        negative_share=0.0,
        trend_pct=trend,
        available=True,
        note=(
            f"Relative search interest (0-100) in {_trends_region()}. Excluded from "
            "sentiment averages: search volume measures attention, not approval."
        ),
    )


def _empty_response(
    query: str, lookback_days: int, provenance: str, warnings: list[str]
) -> SocialResponse:
    return SocialResponse(
        query=query,
        generated_at=datetime.now(UTC),
        lookback_days=lookback_days,
        cached=False,
        provenance=provenance,  # type: ignore[arg-type]
        connectors=[],
        sentiment_model=SentimentModelInfo(
            name="none", kind="lexicon", detail="No documents to score."
        ),
        total_documents=0,
        filtered_documents=0,
        total_mentions=0,
        overall_sentiment=0.0,
        overall_label="neutral",
        platforms=[],
        timeline=build_timeline([], lookback_days),
        trending_terms=[],
        top_documents=[],
        narrative=[],
        narrative_source="none",
        warnings=warnings,
    )


async def sentiment_series_for(query: str, lookback_days: int) -> dict[str, float]:
    """Daily sentiment index for fusion, harvested independently of the API response."""
    settings = get_settings()
    documents, _, _ = await _harvest(query, lookback_days, settings.social_max_documents)
    if not documents:
        replay = fixtures.load_fixture(query)
        if replay:
            documents = replay[0]
    if not documents:
        return {}
    kept, _ = apply_filters(documents, query)
    await score_documents(kept or documents)
    return sentiment_index_series(kept or documents)
