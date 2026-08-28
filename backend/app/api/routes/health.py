"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.config import get_settings
from app.db.session import get_engine
from app.services.forecasting import chronos, chronos2

router = APIRouter()


@router.get("/health", summary="Liveness probe")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/ready", summary="Readiness probe with subsystem detail")
def ready() -> dict:
    settings = get_settings()

    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    return {
        # Readiness tracks the database only. Model weights download lazily on
        # first use, and the service is genuinely able to serve (via the
        # statistical fallback) before that happens.
        "status": "ready" if database_ok else "degraded",
        "version": __version__,
        "environment": settings.environment,
        "database": "ok" if database_ok else "unavailable",
        "forecasting": {
            "default_model": settings.default_model,
            "device": settings.resolve_device(),
            "chronos2": {
                "enabled": settings.chronos2_enabled,
                "model": settings.chronos2_model_id,
                "importable": chronos2.is_available(),
                "supports_covariates": True,
            },
            "chronos_bolt": {
                "enabled": settings.chronos_enabled,
                "model": settings.chronos_model_id,
                "importable": chronos.is_available(),
                "supports_covariates": False,
            },
        },
        "enrichment": {
            "enabled": settings.enrichment_enabled,
            "weather": settings.enrichment_weather_enabled,
            "holidays": settings.enrichment_holidays_enabled,
        },
        "narrative": {
            "enabled": settings.narrative_enabled,
            "model": settings.gemini_model,
            "configured": settings.has_gemini,
        },
        "social": {
            "enabled": settings.social_enabled,
            "connectors": settings.social_connectors,
            "sentiment_model": settings.sentiment_model_id,
            "llm_narrative": settings.has_llm,
        },
    }
