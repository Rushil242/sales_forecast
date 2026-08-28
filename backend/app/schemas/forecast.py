"""Response contracts for the forecasting API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DataQualityLevel = Literal["good", "adequate", "limited", "insufficient"]


class HistoryPoint(BaseModel):
    date: str
    units: float


class ForecastPoint(BaseModel):
    date: str
    predicted_units: float
    lower_80: float
    upper_80: float
    # Null when the serving model cannot produce a 95% interval honestly.
    # Chronos-Bolt's quantile heads are trained only on 0.1-0.9, so asking it for
    # 0.025 returns a clamped 0.1 -- reported as null rather than as a number that
    # would imply knowledge the model does not have.
    lower_95: float | None = None
    upper_95: float | None = None
    # Pre-fusion model output, retained so the sentiment contribution is auditable
    # rather than silently baked into a single number.
    base_units: float
    sentiment_adjustment_pct: float = 0.0


class ModelInfo(BaseModel):
    name: str
    kind: Literal["foundation", "statistical", "naive"]
    detail: str = ""
    device: str | None = None
    # Set when the requested model failed to load and a fallback served the request.
    fell_back_from: str | None = None


class DataQuality(BaseModel):
    observations: int
    span_days: int
    non_zero_days: int
    zero_day_ratio: float
    coverage_ratio: float = Field(description="observed days divided by calendar span")
    level: DataQualityLevel
    warnings: list[str] = Field(default_factory=list)


class MetricSet(BaseModel):
    """Standard point-forecast accuracy metrics.

    MASE is scale-free and comparable across products; MAPE is included because
    it is what business stakeholders expect, despite being unstable near zero.
    """

    mae: float
    rmse: float
    mape: float | None = None
    smape: float
    mase: float | None = None
    coverage_80: float | None = Field(
        default=None, description="share of actuals falling inside the 80% interval"
    )


class BacktestResult(BaseModel):
    windows: int
    horizon: int
    metrics_by_model: dict[str, MetricSet]
    best_model: str
    # Percentage improvement of the chosen model over the seasonal-naive baseline.
    improvement_over_naive_pct: float | None = None
    note: str = ""


class FusionResult(BaseModel):
    applied: bool
    mode: Literal["calibrated", "prior", "disabled", "unavailable"]
    elasticity: float | None = None
    lag_days: int | None = None
    r_squared: float | None = None
    overlap_days: int | None = None
    mean_adjustment_pct: float = 0.0
    max_adjustment_pct: float = 0.0
    sentiment_index_mean: float | None = None
    note: str = ""


class CovariateGroupScore(BaseModel):
    """Measured value of one covariate group on this specific series."""

    group: str
    mase: float | None = None
    delta_pct: float = Field(description="percentage error reduction vs no covariates")
    helps: bool
    reason: str = ""


class CovariateReport(BaseModel):
    """What external signals were attached, and the evidence for attaching them.

    The system does not assume weather or holidays help. It measures each group on
    rolling windows of this series and keeps only those that reduce error, which is
    why ``selected`` is frequently a subset of ``available`` -- and occasionally empty.
    """

    enabled: bool
    available_groups: list[str] = Field(default_factory=list)
    selected_groups: list[str] = Field(default_factory=list)
    columns: list[dict] = Field(default_factory=list)
    scores: list[CovariateGroupScore] = Field(default_factory=list)
    baseline_mase: float | None = None
    selected_mase: float | None = None
    improvement_pct: float = 0.0
    windows: int = 0
    method: Literal["measured", "cached", "skipped", "unavailable", "disabled"] = "disabled"
    location: str | None = None
    note: str = ""
    warnings: list[str] = Field(default_factory=list)


class InsightCard(BaseModel):
    key: str
    label: str
    value: str
    detail: str
    trend: Literal["up", "down", "flat"] = "flat"


class Insights(BaseModel):
    cards: list[InsightCard]
    recommendations: list[str]
    weekday_profile: list[dict[str, float | str]]


class ForecastResponse(BaseModel):
    # ``brief`` is attached after construction by the narrative layer, which needs a
    # complete response to summarise. Optional so the forecast never depends on it.
    run_id: str
    generated_at: datetime
    dataset_name: str
    # For a group forecast this is the group's label ("Upper Wear"), not a SKU.
    product_name: str
    # What was actually selected, so the client can render it and re-run it.
    selection: dict[str, str] = Field(default_factory=dict)
    region: str | None = None
    horizon_days: int

    model_info: ModelInfo
    history: list[HistoryPoint]
    forecast: list[ForecastPoint]
    data_quality: DataQuality
    backtest: BacktestResult | None = None
    covariates: CovariateReport
    fusion: FusionResult
    insights: Insights
    brief: dict | None = None
    timings_ms: dict[str, int]


class ProductSummary(BaseModel):
    product_name: str
    category: str | None = None
    observations: int
    total_units: float
    first_date: str
    last_date: str
    data_quality: DataQualityLevel


class DatasetSummary(BaseModel):
    name: str
    # "connector" is data pulled live from the retailer's own Shopify or Zoho.
    # It is deliberately the same shape as the other two: connector data goes
    # through the identical ingestion and data-quality gate, with no shortcuts.
    source: Literal["bundled", "upload", "connector"]
    rows: int
    products: int
    regions: list[str]
    first_date: str
    last_date: str
    span_days: int
    columns: list[str]
    description: str = ""
    # Present only for connector datasets: which account this came from.
    connector: dict[str, str] | None = None


class DatasetDetail(DatasetSummary):
    product_list: list[ProductSummary]
