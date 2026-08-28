"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import connectors, forecast, health, social
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging_config import configure_logging, new_request_id, request_id_var
from app.db.session import init_db

LOG = logging.getLogger(__name__)

DESCRIPTION = """
Retail demand intelligence: zero-shot time-series foundation-model forecasting,
fused with an agentic social-sentiment pipeline.

**Design commitments**

* No synthetic history. A series too short to forecast returns
  `422 insufficient_data` rather than a result padded with invented observations.
* Every forecast is backtested against statistical baselines over rolling
  origins, and the metrics are returned with the forecast.
* Social figures carry their provenance (`live`, `fixture`, `cache`, `none`) and
  a per-connector status, so it is always visible what the numbers rest on.
* Sentiment fusion reports whether its elasticity was calibrated from data or
  taken from a bounded prior, and the un-fused base forecast is always returned
  alongside the adjusted one.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, as_json=settings.log_json)
    LOG.info("Starting RetailIQ %s in %s mode", __version__, settings.environment)
    init_db()
    LOG.info(
        "Forecasting: chronos=%s (%s) | Social: %s | Sentiment: %s",
        settings.chronos_enabled, settings.resolve_device(),
        ",".join(settings.social_connectors), settings.sentiment_model_id,
    )
    yield
    LOG.info("Shutting down")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="RetailIQ API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Attach a correlation id and timing to every request."""
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Handlers registered below cannot see exceptions raised inside
            # middleware, so this is the last line of defence for the header.
            LOG.exception("Request failed: %s %s", request.method, request.url.path)
            response = JSONResponse(
                status_code=500,
                content={"error": {"code": "internal_error",
                                   "message": "An unexpected internal error occurred.",
                                   "request_id": request_id}},
            )
        finally:
            request_id_var.reset(token)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)

        if request.url.path not in {"/health", "/ready"}:
            LOG.info("%s %s -> %d in %d ms",
                     request.method, request.url.path, response.status_code, elapsed_ms)
        return response

    register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(forecast.router, prefix=settings.api_prefix, tags=["forecast"])
    app.include_router(social.router, prefix=settings.api_prefix, tags=["social"])
    app.include_router(connectors.router, prefix=settings.api_prefix, tags=["connectors"])

    return app


app = create_app()
