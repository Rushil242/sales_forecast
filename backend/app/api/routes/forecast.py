"""Forecasting endpoints."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError, UploadTooLargeError
from app.db.session import get_db
from app.schemas.forecast import DatasetDetail, DatasetSummary, ForecastResponse
from app.services import datasets
from app.services.forecast_service import generate_forecast
from app.services.forecasting.registry import list_models
from app.services.social.agent import sentiment_series_for

LOG = logging.getLogger(__name__)
router = APIRouter()


class ForecastRequest(BaseModel):
    dataset: str = Field(
        default="online-retail-ii",
        description="A bundled dataset key, or an upload token from POST /datasets/upload.",
    )
    product_name: str | None = Field(
        default=None,
        description="A single product. Omit it and pass `filters` to forecast a "
                    "whole group instead.",
    )
    filters: dict[str, str] = Field(
        default_factory=dict,
        description='Group selector, e.g. {"category": "Upper Wear"}. The series '
                    'becomes the summed daily demand of everything matching. Leave '
                    'both this and product_name empty to forecast the whole dataset.',
    )
    horizon_days: int = Field(default=30, ge=1, le=180)
    model: str | None = Field(
        default=None, description="Model name; defaults to chronos-bolt."
    )
    region: str | None = None
    include_backtest: bool = True
    backtest_windows: int | None = Field(default=None, ge=1, le=12)
    include_covariates: bool = Field(
        default=True,
        description='Fetch weather/holiday/calendar signals, measure which help this '
                    'series, and attach only those. Requires a covariate-capable model.',
    )
    include_brief: bool = Field(
        default=True,
        description="Generate the plain-English owner brief. Uses Gemini when a key is "
                    "configured, otherwise a deterministic template.",
    )
    include_sentiment: bool = Field(
        default=False,
        description="Harvest social sentiment and fuse it into the forecast. "
                    "Adds several seconds; the un-fused base forecast is returned "
                    "alongside the adjusted one either way.",
    )


@router.get("/models", summary="List available forecasting models")
def get_models() -> list[dict]:
    return list_models()


@router.get(
    "/datasets",
    response_model=list[DatasetSummary],
    summary="List bundled datasets and synced connections",
)
def get_datasets() -> list[DatasetSummary]:
    # Connected accounts come first: if someone has plugged in their own Shopify,
    # that is the dataset they came to look at, not the bundled sample.
    return datasets.list_connected() + datasets.list_bundled()


# Declared before the generic /datasets/{identifier:path} route below: `:path` is
# greedy, so it would otherwise swallow "…/taxonomy" as part of the dataset id.
@router.get(
    "/datasets/{identifier:path}/taxonomy",
    summary="Browse tree: how this dataset can be sliced, with per-node quality",
)
def get_taxonomy(identifier: str) -> dict:
    from app.services.taxonomy import build_taxonomy

    return build_taxonomy(datasets.resolve(identifier))


@router.get(
    "/datasets/{identifier:path}",
    response_model=DatasetDetail,
    summary="Describe a dataset and its products",
)
def get_dataset(identifier: str) -> DatasetDetail:
    return datasets.describe(identifier)


@router.post("/datasets/upload", summary="Upload a transactional CSV")
async def upload_dataset(file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise UploadTooLargeError(
            f"File is {len(content) / 1e6:.1f} MB; the limit is "
            f"{settings.max_upload_bytes / 1e6:.0f} MB.",
            size_bytes=len(content),
        )

    token, dataset = datasets.store_upload(content, file.filename or "upload.csv")
    detail = datasets.describe(token)
    return {
        "token": token,
        "dataset": detail.model_dump(),
        "warnings": dataset.warnings,
        "resolved_columns": dataset.column_map,
    }


@router.post("/forecast", response_model=ForecastResponse, summary="Generate a demand forecast")
async def create_forecast(
    request: ForecastRequest,
    session: Session = Depends(get_db),
) -> ForecastResponse:
    dataset = datasets.resolve(request.dataset)

    sentiment: dict[str, float] = {}
    if request.include_sentiment:
        settings = get_settings()
        # A group has no single name to search for, so the group's own label is
        # the query -- "Upper Wear" is at least what the user asked about.
        query = request.product_name or " ".join(request.filters.values())
        try:
            sentiment = await sentiment_series_for(
                query, settings.social_lookback_days
            )
        except Exception as exc:
            # Sentiment is an enhancement. Losing it must not cost the user their
            # forecast; the response reports fusion as unavailable instead.
            LOG.warning("Sentiment harvest failed for %r: %s", query, exc)

    return generate_forecast(
        dataset,
        product_name=request.product_name,
        horizon=request.horizon_days,
        model_name=request.model,
        region=request.region,
        filters=request.filters or None,
        run_backtest_flag=request.include_backtest,
        backtest_windows=request.backtest_windows,
        sentiment=sentiment,
        use_covariates=request.include_covariates,
        include_brief=request.include_brief,
        session=session,
    )


@router.post("/forecast/stream", summary="Generate a forecast, streaming real progress")
async def create_forecast_stream(
    request: ForecastRequest,
    session: Session = Depends(get_db),
) -> StreamingResponse:
    """Server-sent events carrying the pipeline's own stage transitions.

    The stages are emitted from inside ``generate_forecast`` as each one begins, so
    what the user watches is the work actually happening rather than a timer
    pretending to be one. A skipped stage -- no backtest, no covariates -- simply
    never arrives, which is why the client must render whatever it is sent instead
    of a fixed checklist.
    """
    dataset = datasets.resolve(request.dataset)
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_stage(stage: str, detail: str) -> None:
        # Called from the worker thread; hop back onto the loop to enqueue.
        loop.call_soon_threadsafe(
            queue.put_nowait,
            json.dumps({"type": "stage", "stage": stage, "detail": detail}),
        )

    async def run() -> None:
        sentiment: dict[str, float] = {}
        try:
            if request.include_sentiment:
                settings = get_settings()
                query = request.product_name or " ".join(request.filters.values())
                on_stage("sentiment",
                         f"Harvesting public discussion about {query} across every "
                         "reachable source")
                try:
                    sentiment = await sentiment_series_for(
                        query, settings.social_lookback_days
                    )
                except Exception as exc:
                    LOG.warning("Sentiment harvest failed for %r: %s", query, exc)

            response = await asyncio.to_thread(
                generate_forecast,
                dataset,
                product_name=request.product_name,
                horizon=request.horizon_days,
                model_name=request.model,
                region=request.region,
                filters=request.filters or None,
                run_backtest_flag=request.include_backtest,
                backtest_windows=request.backtest_windows,
                sentiment=sentiment,
                use_covariates=request.include_covariates,
                include_brief=request.include_brief,
                session=None,
                on_stage=on_stage,
            )
            queue.put_nowait(json.dumps({
                "type": "done", "result": response.model_dump(mode="json"),
            }))
        except AppError as exc:
            queue.put_nowait(json.dumps({"type": "error", "error": exc.to_payload()["error"]}))
        except Exception as exc:
            LOG.exception("Streamed forecast failed")
            queue.put_nowait(json.dumps({
                "type": "error",
                "error": {"code": "internal_error", "message": str(exc)},
            }))
        finally:
            queue.put_nowait("__end__")

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                payload = await queue.get()
                if payload == "__end__":
                    break
                yield f"data: {payload}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/forecast/upload",
    response_model=ForecastResponse,
    summary="Upload a CSV and forecast in one request",
)
async def forecast_from_upload(
    file: UploadFile = File(...),
    product_name: str = Form(...),
    horizon_days: int = Form(30),
    model: str | None = Form(None),
    include_backtest: bool = Form(True),
    session: Session = Depends(get_db),
) -> ForecastResponse:
    """Single-call convenience path, mirroring the original API shape."""
    settings = get_settings()
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise UploadTooLargeError(size_bytes=len(content))

    _, dataset = datasets.store_upload(content, file.filename or "upload.csv")
    return generate_forecast(
        dataset,
        product_name=product_name,
        horizon=min(max(horizon_days, 1), settings.forecast_max_horizon),
        model_name=model,
        run_backtest_flag=include_backtest,
        session=session,
    )


@router.get("/runs", summary="Recent forecast runs (audit trail)")
def list_runs(
    limit: int = Query(default=25, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[dict]:
    from sqlalchemy import select

    from app.db.models import ForecastRun

    runs = session.execute(
        select(ForecastRun).order_by(ForecastRun.created_at.desc()).limit(limit)
    ).scalars().all()

    return [
        {
            "id": run.id,
            "created_at": run.created_at.isoformat(),
            "dataset": run.dataset_name,
            "product_name": run.product_name,
            "model": run.model_name,
            "horizon_days": run.horizon_days,
            "observations": run.observations,
            "mean_predicted_units": round(run.mean_predicted_units, 2),
            "fusion_mode": run.fusion_mode,
            "duration_ms": run.duration_ms,
            "backtest": run.backtest_metrics,
        }
        for run in runs
    ]
