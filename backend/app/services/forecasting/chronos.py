"""Amazon Chronos-Bolt adapter -- the zero-shot time-series foundation model.

Chronos-Bolt is a patched encoder-decoder T5 trained on a large corpus of time
series. It forecasts a previously-unseen series with no fitting step, which is
exactly the "zero-shot TSFM" capability the project set out to demonstrate.

Two practical notes:

* Bolt emits **quantiles directly** from dedicated output heads, so there is no
  sampling variance and no need to draw hundreds of trajectories. It is roughly
  an order of magnitude faster than the original sampling-based Chronos-T5.
* The pipeline is loaded lazily and memoised per process. Loading costs a few
  seconds and ~200 MB; doing it at import time would make the whole API fail to
  start on a machine with no model cache.
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


def load_pipeline() -> Any:
    """Load and memoise the Chronos pipeline. Raises ``ModelUnavailableError`` on failure."""
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
            from chronos import BaseChronosPipeline

            device = settings.resolve_device()
            LOG.info("Loading %s on %s (first run downloads ~200 MB)",
                     settings.chronos_model_id, device)
            _pipeline = BaseChronosPipeline.from_pretrained(
                settings.chronos_model_id,
                device_map=device,
                # bfloat16 is unsupported on MPS and on older CPUs; float32 is
                # the portable choice and the model is small enough not to care.
                torch_dtype=torch.float32,
            )
            LOG.info("Chronos ready: %s", settings.chronos_model_id)
            return _pipeline
        except Exception as exc:
            _pipeline_error = (
                f"Could not load {settings.chronos_model_id}: {exc}. "
                "Statistical models remain available."
            )
            LOG.warning("%s", _pipeline_error)
            raise ModelUnavailableError(_pipeline_error) from exc


def reset_pipeline() -> None:
    """Clear the memoised pipeline and any recorded load failure (used by tests)."""
    global _pipeline, _pipeline_error
    with _lock:
        _pipeline = None
        _pipeline_error = None


def is_available() -> bool:
    """Cheap check that never triggers a download."""
    settings = get_settings()
    if not settings.chronos_enabled:
        return False
    if _pipeline is not None:
        return True
    if _pipeline_error is not None:
        return False
    try:
        import chronos  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


class ChronosForecaster(Forecaster):
    name = "chronos-bolt"
    kind = "foundation"

    def __init__(self) -> None:
        settings = get_settings()
        self.model_id = settings.chronos_model_id
        self.context_length = settings.chronos_context_length
        self.device = settings.resolve_device()
        self.detail = f"{self.model_id} (zero-shot, {self.device})"

    @property
    def available(self) -> bool:
        return is_available()

    @staticmethod
    def _supported_levels(pipeline: Any) -> list[float]:
        """Intersect the levels we want with the ones this checkpoint can produce.

        Chronos-Bolt exposes its trained quantile grid as ``pipeline.quantiles``
        (0.1 ... 0.9 for the released checkpoints). Sampling-based Chronos-T5
        pipelines have no such attribute and can produce any level, so in that
        case we ask for everything.
        """
        trained = getattr(pipeline, "quantiles", None)
        if not trained:
            from app.services.forecasting.base import EXTENDED_QUANTILES

            return sorted({*CORE_QUANTILES, *EXTENDED_QUANTILES})
        low, high = min(trained), max(trained)
        return [level for level in CORE_QUANTILES if low <= level <= high]

    def predict(
        self,
        series: pd.Series,
        horizon: int,
        covariates: CovariateFrame | None = None,
    ) -> ForecastOutput:
        # Univariate by construction: Chronos-Bolt has no covariate input at all.
        # That is precisely why chronos2.py exists.
        import torch

        pipeline = load_pipeline()

        # Chronos attends over a bounded context; feeding more than the model was
        # trained to see wastes memory without improving accuracy.
        context_values = series.values[-self.context_length:].astype("float32")
        context = torch.tensor(context_values, dtype=torch.float32)

        # Only ask for levels the checkpoint was actually trained on. Requesting
        # anything outside that range makes Chronos clamp to its nearest trained
        # head and warn -- yielding, for example, a "95%" interval numerically
        # identical to the 80% one. Omitting the level is the honest alternative.
        levels = self._supported_levels(pipeline)

        # The first argument is passed positionally on purpose: chronos-forecasting
        # renamed it from `context` to `inputs` in 2.x, and positional binding works
        # against both generations of the library.
        quantile_tensor, mean_tensor = pipeline.predict_quantiles(
            context,
            prediction_length=horizon,
            quantile_levels=levels,
        )

        # Shapes: quantiles (batch, horizon, n_levels), mean (batch, horizon).
        quantile_array = quantile_tensor[0].float().cpu().numpy()
        mean = mean_tensor[0].float().cpu().numpy().astype("float64")
        quantiles = {
            level: quantile_array[:, i].astype("float64") for i, level in enumerate(levels)
        }

        output = ForecastOutput(
            index=self.future_index(series, horizon),
            mean=np.asarray(mean, dtype="float64"),
            quantiles=quantiles,
        )
        return output.enforce_monotonic_quantiles().clipped()
