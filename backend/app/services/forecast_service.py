"""Forecast orchestration: the pipeline behind ``POST /forecast``."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ForecastRun
from app.schemas.forecast import (
    CovariateGroupScore,
    CovariateReport,
    DataQuality,
    ForecastPoint,
    ForecastResponse,
    FusionResult,
    HistoryPoint,
    ModelInfo,
)
from app.services.enrichment import geo
from app.services.enrichment.base import CovariateFrame
from app.services.enrichment.builder import build_covariates
from app.services.forecasting.backtest import run_backtest
from app.services.forecasting.base import ForecastOutput
from app.services.forecasting.covariate_selection import (
    load_cached,
    select_covariates,
    store_cached,
)
from app.services.forecasting.fusion import apply_fusion
from app.services.forecasting.registry import build_registry, get_forecaster
from app.services.ingestion import Dataset
from app.services.insights import build_insights
from app.services.narrative.briefing import build_brief
from app.services.series import assess_quality, build_daily_series, require_forecastable

LOG = logging.getLogger(__name__)


def _to_points(
    base: ForecastOutput, fused: ForecastOutput
) -> list[ForecastPoint]:
    """Serialise a forecast, keeping the pre-fusion values alongside the final ones."""
    points: list[ForecastPoint] = []
    for i, timestamp in enumerate(fused.index):
        base_value = float(base.mean[i])
        final_value = float(fused.mean[i])
        adjustment = (final_value / base_value - 1.0) * 100 if base_value > 0 else 0.0
        points.append(
            ForecastPoint(
                date=timestamp.strftime("%Y-%m-%d"),
                predicted_units=round(final_value, 3),
                lower_80=round(float(fused.quantiles[0.1][i]), 3),
                upper_80=round(float(fused.quantiles[0.9][i]), 3),
                lower_95=(
                    round(float(fused.quantiles[0.025][i]), 3) if fused.has_95 else None
                ),
                upper_95=(
                    round(float(fused.quantiles[0.975][i]), 3) if fused.has_95 else None
                ),
                base_units=round(base_value, 3),
                sentiment_adjustment_pct=round(adjustment, 3),
            )
        )
    return points


def _persist(
    session: Session,
    dataset: Dataset,
    response: ForecastResponse,
    quality: DataQuality,
    duration_ms: int,
) -> None:
    predicted = [p.predicted_units for p in response.forecast]
    run = ForecastRun(
        id=response.run_id,
        dataset_name=dataset.name,
        series_fingerprint=dataset.fingerprint(),
        product_name=response.product_name,
        region=response.region,
        model_name=response.model_info.name,
        horizon_days=response.horizon_days,
        observations=quality.observations,
        history_start=response.history[0].date if response.history else "",
        history_end=response.history[-1].date if response.history else "",
        fusion_applied=response.fusion.applied,
        fusion_elasticity=response.fusion.elasticity,
        fusion_mode=response.fusion.mode,
        total_predicted_units=sum(predicted),
        mean_predicted_units=sum(predicted) / len(predicted) if predicted else 0.0,
        backtest_metrics=(
            response.backtest.model_dump(mode="json") if response.backtest else None
        ),
        data_quality=quality.model_dump(mode="json"),
        duration_ms=duration_ms,
    )
    session.add(run)
    session.commit()


def resolve_covariates(
    *,
    series,
    horizon: int,
    forecaster,
    dataset: Dataset,
    region: str | None,
    sentiment: dict[str, float] | None,
    enabled: bool,
) -> tuple[CovariateFrame | None, CovariateReport]:
    """Fetch external signals, measure which ones help, and keep only those.

    Returns the frame actually passed to the model plus a full account of the
    decision. The measurement is cached per (series, horizon) because it costs
    several seconds -- far too slow to repeat on every request.
    """
    if not enabled:
        return None, CovariateReport(
            enabled=False, method="disabled",
            note="External signals were not requested for this forecast.",
        )
    if not forecaster.supports_covariates:
        return None, CovariateReport(
            enabled=True, method="unavailable",
            note=f"{forecaster.name} is univariate and cannot consume external signals. "
                 "Select chronos-2 to use weather, holidays or sentiment.",
        )

    effective_region = region or geo.dominant_region(dataset.frame)
    location = geo.resolve(effective_region)
    future_index = pd.date_range(
        series.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D"
    )

    def build(train_index, horizon_index) -> CovariateFrame:
        return build_covariates(
            train_index, horizon_index, location, sentiment=sentiment,
        )

    try:
        full = build(pd.DatetimeIndex(series.index), future_index)
    except Exception as exc:
        LOG.warning("Covariate build failed: %s", exc)
        return None, CovariateReport(
            enabled=True, method="unavailable", location=str(location),
            note=f"External signals could not be fetched ({exc}).",
        )

    available = full.groups
    if not available:
        return None, CovariateReport(
            enabled=True, method="unavailable", location=str(location),
            note="No external signal source returned usable data.",
            warnings=full.warnings,
        )

    selection = load_cached(series, horizon, available)
    if selection is None:
        selection = select_covariates(
            forecaster, series, horizon, build,
            available_groups=available,
        )
        if selection.method == "measured":
            store_cached(series, horizon, available, selection)

    chosen = full.only(selection.selected) if selection.selected else None

    report = CovariateReport(
        enabled=True,
        available_groups=available,
        selected_groups=selection.selected,
        columns=chosen.describe() if chosen else [],
        scores=[
            CovariateGroupScore(
                group=s.group,
                mase=None if s.mase != s.mase else s.mase,  # NaN -> None
                delta_pct=s.delta_pct, helps=s.helps, reason=s.reason,
            )
            for s in selection.scores
        ],
        baseline_mase=selection.baseline_mase,
        selected_mase=selection.selected_mase,
        improvement_pct=selection.improvement_pct,
        windows=selection.windows,
        method=selection.method,  # type: ignore[arg-type]
        location=str(location),
        note=selection.note,
        warnings=full.warnings,
    )
    return chosen, report


def generate_forecast(
    dataset: Dataset,
    product_name: str | None,
    horizon: int,
    *,
    model_name: str | None = None,
    region: str | None = None,
    filters: dict[str, str] | None = None,
    run_backtest_flag: bool = True,
    backtest_windows: int | None = None,
    sentiment: dict[str, float] | None = None,
    use_covariates: bool = True,
    include_brief: bool = True,
    session: Session | None = None,
    history_limit: int | None = 365,
    on_stage: Callable[[str, str], None] | None = None,
) -> ForecastResponse:
    """Run the full forecasting pipeline for one product, or for a group.

    ``filters`` selects a group -- a category, a colour, a market, or a
    combination -- and the series becomes the summed daily demand of everything
    inside it. That is the level most buying decisions are actually made at, and
    it is frequently *more* forecastable than any single SKU within it.
    """
    settings = get_settings()
    started = time.perf_counter()
    timings: dict[str, int] = {}

    def mark(stage: str, since: float) -> float:
        now = time.perf_counter()
        timings[stage] = int((now - since) * 1000)
        return now

    def announce(stage: str, detail: str) -> None:
        """Report a stage as it *starts*.

        Emitted from inside the pipeline rather than guessed by the client, so the
        progress a user watches corresponds to work that is actually happening. A
        stage that is skipped is never announced.
        """
        if on_stage is not None:
            try:
                on_stage(stage, detail)
            except Exception:  # a listener must never break the forecast
                LOG.debug("progress listener failed for stage %s", stage)

    checkpoint = started
    from app.services.taxonomy import describe_selection

    label = describe_selection(dataset, product_name, filters)
    announce("series", f"Building the daily demand series for {label}")
    series = build_daily_series(dataset, product_name, region, filters)
    quality = assess_quality(series)
    require_forecastable(series, quality, label)
    checkpoint = mark("series", checkpoint)

    forecaster, fell_back_from = get_forecaster(model_name)
    if use_covariates and settings.enrichment_enabled and forecaster.supports_covariates:
        announce("covariates",
                 "Fetching weather and holiday signals, then measuring which ones "
                 "actually improve accuracy on this series")

    covariates, covariate_report = resolve_covariates(
        series=series,
        horizon=horizon,
        forecaster=forecaster,
        dataset=dataset,
        region=region,
        sentiment=sentiment,
        enabled=use_covariates and settings.enrichment_enabled,
    )
    checkpoint = mark("covariates", checkpoint)

    announce("forecast", f"Running {forecaster.name} over a {horizon}-day horizon")
    base_forecast = forecaster.predict(series, horizon, covariates)
    checkpoint = mark("forecast", checkpoint)

    # Fusion is now the fallback path: when the model can consume sentiment as a
    # covariate there is no need to scale its output afterwards.
    if forecaster.supports_covariates and "sentiment" in covariate_report.selected_groups:
        fused_forecast = base_forecast
        fusion_result = FusionResult(
            applied=False, mode="disabled",
            note="Sentiment entered the model directly as a covariate, so no post-hoc "
                 "adjustment was applied.",
        )
    else:
        fused_forecast, fusion_result = apply_fusion(base_forecast, series, sentiment or {})
    checkpoint = mark("fusion", checkpoint)

    backtest = None
    if run_backtest_flag:
        windows = min(
            backtest_windows or settings.backtest_windows, settings.backtest_max_windows
        )
        announce("backtest", "Backtesting against five statistical baselines on rolling windows")
        backtest = run_backtest(
            series, list(build_registry().values()), horizon, windows,
            covariates=covariates,
        )
        checkpoint = mark("backtest", checkpoint)

    points = _to_points(base_forecast, fused_forecast)
    insights = build_insights(series, points, quality, backtest, product_name)

    # Long histories make for an unreadable chart and a large payload; the tail is
    # what a reader is actually looking at next to the forecast.
    display_series = series.iloc[-history_limit:] if history_limit else series
    history = [
        HistoryPoint(date=timestamp.strftime("%Y-%m-%d"), units=round(float(value), 3))
        for timestamp, value in display_series.items()
    ]

    duration_ms = int((time.perf_counter() - started) * 1000)
    timings["total"] = duration_ms

    response = ForecastResponse(
        run_id=_new_run_id(),
        generated_at=datetime.now(UTC),
        dataset_name=dataset.name,
        # For a group forecast this is the group's label, so every downstream
        # consumer -- the brief, the audit row, the chart title -- names what was
        # actually forecast rather than saying "None".
        product_name=label,
        selection=(
            {"kind": "product", "product_name": product_name} if product_name
            else {"kind": "group", **{k: str(v) for k, v in (filters or {}).items()}}
        ),
        region=region,
        horizon_days=horizon,
        model_info=ModelInfo(
            name=forecaster.name,
            kind=forecaster.kind,  # type: ignore[arg-type]
            detail=forecaster.detail,
            device=getattr(forecaster, "device", None),
            fell_back_from=fell_back_from,
        ),
        history=history,
        forecast=points,
        data_quality=quality,
        backtest=backtest,
        covariates=covariate_report,
        fusion=fusion_result,
        insights=insights,
        timings_ms=timings,
    )

    if include_brief:
        announce("brief", "Writing the plain-English brief and checking every figure "
                          "in it against the measured data")
        brief_started = time.perf_counter()
        try:
            response.brief = build_brief(response).model_dump(mode="json")
        except Exception as exc:
            # A missing brief must never cost the user their forecast.
            LOG.warning("Could not build the owner brief: %s", exc)
        timings["brief"] = int((time.perf_counter() - brief_started) * 1000)
        timings["total"] = int((time.perf_counter() - started) * 1000)
        response.timings_ms = timings

    LOG.info(
        "Forecast: selection=%r model=%s horizon=%d obs=%d covariates=[%s] in %d ms",
        label, forecaster.name, horizon, quality.observations,
        ",".join(covariate_report.selected_groups) or "none", duration_ms,
    )

    if session is not None:
        try:
            _persist(session, dataset, response, quality, duration_ms)
        except Exception as exc:
            # A failed audit write must not lose the user their forecast.
            LOG.warning("Could not persist forecast run: %s", exc)
            session.rollback()

    return response


def _new_run_id() -> str:
    import uuid

    return uuid.uuid4().hex


def summarise_products(dataset: Dataset, limit: int = 200) -> list[dict]:
    """Per-product profile used to populate the product picker."""
    frame = dataset.frame
    grouped = frame.groupby("product").agg(
        observations=("date", "nunique"),
        total_units=("units", "sum"),
        first_date=("date", "min"),
        last_date=("date", "max"),
    )
    if "category" in frame.columns:
        categories = frame.groupby("product")["category"].first()
    else:
        categories = pd.Series(dtype="object")

    settings = get_settings()
    summaries: list[dict] = []
    for product, row in grouped.sort_values("total_units", ascending=False).head(limit).iterrows():
        span = (row["last_date"] - row["first_date"]).days + 1
        if span < settings.min_observations:
            level = "insufficient"
        elif span < settings.recommended_observations:
            level = "limited"
        elif span < 2 * settings.recommended_observations:
            level = "adequate"
        else:
            level = "good"

        summaries.append({
            "product_name": str(product),
            "category": str(categories.get(product)) if len(categories) else None,
            "observations": int(row["observations"]),
            "total_units": float(row["total_units"]),
            "first_date": row["first_date"].strftime("%Y-%m-%d"),
            "last_date": row["last_date"].strftime("%Y-%m-%d"),
            "data_quality": level,
        })
    return summaries
