"""Social intelligence endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.schemas.social import SocialResponse
from app.services.social import fixtures
from app.services.social.agent import DOCUMENT_CONNECTORS, SIGNAL_CONNECTORS, analyse
from app.services.social.fetchers import engine_status

LOG = logging.getLogger(__name__)
router = APIRouter()


@router.get("/social", response_model=SocialResponse, summary="Analyse social signal for a product")
async def get_social(
    query: str = Query(..., min_length=2, description="Product or brand to analyse"),
    lookback_days: int = Query(default=30, ge=1, le=90),
    refresh: bool = Query(default=False, description="Bypass the cache and re-harvest"),
    session: Session = Depends(get_db),
) -> SocialResponse:
    return await analyse(query, session, lookback_days, use_cache=not refresh)


@router.get("/social/connectors", summary="Connector inventory and configuration state")
async def get_connectors() -> dict:
    settings = get_settings()
    inventory = []

    # Sources that need a key or a browser say so here, before anyone runs a
    # harvest and wonders why a platform is missing from the results.
    needs_credentials = {
        "reddit": not settings.has_reddit_oauth,
        "instagram": not settings.has_apify,
        "x": not settings.has_apify,
    }

    for name, connector_class in {**DOCUMENT_CONNECTORS, **SIGNAL_CONNECTORS}.items():
        connector = connector_class()
        available = await connector.is_available()
        inventory.append({
            "name": name,
            "platform": connector.platform,
            "kind": "signal" if name in SIGNAL_CONNECTORS else "document",
            "enabled": name in settings.social_connectors,
            "available": available,
            "reason": "" if available else connector.unavailable_reason(),
            "requires_credentials": needs_credentials.get(name, False),
        })

    return {
        "connectors": inventory,
        "sentiment_model": settings.sentiment_model_id,
        "llm_narrative_enabled": settings.has_llm,
        "recorded_fixtures": fixtures.available_fixtures(),
        "cache_ttl_seconds": settings.social_cache_ttl_seconds,
        "scraping": engine_status(),
    }
