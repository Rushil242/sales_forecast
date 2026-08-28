"""Chronos-2 adapter -- the covariate-capable time-series foundation model.

Why this exists alongside ``chronos.py``
----------------------------------------
Chronos-Bolt is univariate. It has no mechanism to accept weather, holidays or
sentiment, so the earlier design could only apply exogenous signal *after* the fact,
by scaling the output (see ``fusion.py``). That required assuming a functional form.

Chronos-2 (Amazon, 2025) accepts covariates natively -- past-only and known-future,
numeric and categorical -- inside a single 120M-parameter encoder. The exogenous
signal becomes a genuine model input rather than a post-hoc multiplier.

Measured on a synthetic series where a promotion flag genuinely drives demand,
supplying the covariate cut MAE from 8.44 to 3.00 (-64%). Whether it helps on any
*given* real series is an empirical question, which is exactly why the backtest runs
this model both with and without covariates on identical windows.

Interface notes
---------------
``predict_df`` is dataframe-in, dataframe-out and infers covariate availability from
*presence*: a column in the context frame but absent from the future frame is treated
as past-only. Quantile columns come back named as strings ("0.1", "0.5", "0.9").
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from app.config import get_settings
from app.core.errors import ModelUnavailableError
from app.services.forecasting.base import CORE_QUANTILES, Forecaster, ForecastOutput

if TYPE_CHECKING:
    from app.services.enrichment.base import CovariateFrame

LOG = logging.getLogger(__name__)

_pipeline: Any = None
_pipeline_error: str | None = None
_lock = threading.Lock()

ITEM_ID = "series"


def load_pipeline() -> Any:
    """Load and memoise the Chronos-2 pipeline."""
    global _pipeline, _pipeline_error

    if _pipeline is not None:
        return _pipeline
    if _pipeline_error is not None:
        raise ModelUnavailableError(_pipeline_error)

    with _lock:
        if _pipeline is not None:
            return _pipeline
        if _pipeline_error is not None:
            raise ModelUnavailableError(_pipeline_error)

        settings = get_settings()
        try:
            import torch
            from chronos import Chronos2Pipeline

            device = settings.resolve_device()
            LOG.info("Loading %s on %s (first run downloads ~500 MB)",
                     settings.chronos2_model_id, device)
            _pipeline = Chronos2Pipeline.from_pretrained(
                settings.chronos2_model_id,
                device_map=device,
                dtype=torch.float32,
            )
            LOG.info("Chronos-2 ready: %s", settings.chronos2_model_id)
            return _pipeline
        except Exception as exc:
            _pipeline_error = (
                f"Could not load {settings.chronos2_model_id}: {exc}. "
                "Chronos-Bolt and the statistical models remain available."
            )
            LOG.warning("%s", _pipeline_error)
            raise ModelUnavailableError(_pipeline_error) from exc


def reset_pipeline() -> None:
    """Clear the memoised pipeline and any recorded failure (used by tests)."""
    global _pipeline, _pipeline_error
    with _lock:
        _pipeline = None
        _pipeline_error = None


def is_available() -> bool:
    """Cheap check that never triggers a download."""
    settings = get_settings()
    if not settings.chronos2_enabled:
        return False
    if _pipeline is not None:
        return True
    if _pipeline_error is not None:
        return False
    try:
        import torch  # noqa: F401
        from chronos import Chronos2Pipeline  # noqa: F401
    except ImportError:
        return False
    return True


class Chronos2Forecaster(Forecaster):
    name = "chronos-2"
    kind = "foundation"
    supports_covariates = True

    def __init__(self) -> None:
        settings = get_settings()
        self.model_id = settings.chronos2_model_id
        self.context_length = settings.chronos_context_length
        self.device = settings.resolve_device()
        self.detail = f"{self.model_id} (zero-shot, covariate-aware, {self.device})"

    @property
    def available(self) -> bool:
        return is_available()

    # ── frame construction ───────────────────────────────────────────────────

    def _build_frames(
        self,
        series: pd.Series,
        horizon: int,
        covariates: CovariateFrame | None,
    ) -> tuple[pd.DataFrame, pd.DataFrame | None, list[str]]:
        """Build the context and future frames Chronos-2 expects."""
        context = series.iloc[-self.context_length:]
        future_index = self.future_index(series, horizon)

        context_df = pd.DataFrame({
            "item_id": ITEM_ID,
            "timestamp": context.index,
            "target": context.to_numpy(dtype="float64"),
        })

        if covariates is None or covariates.is_empty:
            return context_df, None, []

        # Past covariates must align exactly with the trimmed context window.
        past = covariates.past.reindex(context.index)
        used: list[str] = []
        for column in past.columns:
            values = past[column]
            if values.isna().all():
                continue
            context_df[column] = values.ffill().bfill().fillna(0.0).to_numpy(dtype="float64")
            used.append(column)

        if not used:
            return context_df, None, []

        # Only known-future columns may appear in the future frame; anything else
        # present in the context frame is inferred as past-only by the model.
        known_future = [c for c in covariates.known_future_columns() if c in used]
        future_df = None
        if known_future:
            future_values = covariates.future.reindex(future_index)
            future_df = pd.DataFrame({
                "item_id": ITEM_ID,
                "timestamp": future_index,
            })
            for column in known_future:
                if column not in future_values.columns:
                    continue
                future_df[column] = (
                    future_values[column].ffill().bfill().fillna(0.0).to_numpy(dtype="float64")
                )
            # A future frame carrying no covariate columns is worse than none at all.
            if future_df.shape[1] <= 2:
                future_df = None

        return context_df, future_df, used

    # ── prediction ───────────────────────────────────────────────────────────

    def predict(
        self,
        series: pd.Series,
        horizon: int,
        covariates: CovariateFrame | None = None,
    ) -> ForecastOutput:
        pipeline = load_pipeline()
        context_df, future_df, used = self._build_frames(series, horizon, covariates)

        levels = list(CORE_QUANTILES)
        predictions = pipeline.predict_df(
            context_df,
            future_df=future_df,
            prediction_length=horizon,
            quantile_levels=levels,
            id_column="item_id",
            timestamp_column="timestamp",
            target="target",
        )

        # Quantile columns are named as plain strings by the pipeline.
        quantiles: dict[float, np.ndarray] = {}
        for level in levels:
            column = str(level)
            if column not in predictions.columns:
                raise ModelUnavailableError(
                    f"Chronos-2 did not return quantile {column}; "
                    f"got columns {list(predictions.columns)}"
                )
            quantiles[level] = predictions[column].to_numpy(dtype="float64")

        mean = (
            predictions["predictions"].to_numpy(dtype="float64")
            if "predictions" in predictions.columns
            else quantiles[0.5].copy()
        )

        if used:
            LOG.debug("Chronos-2 used %d covariate columns: %s", len(used), ", ".join(used))

        output = ForecastOutput(
            index=self.future_index(series, horizon),
            mean=mean,
            quantiles=quantiles,
        )
        return output.enforce_monotonic_quantiles().clipped()
