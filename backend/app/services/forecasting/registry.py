"""Model registry with explicit, reported fallback."""

from __future__ import annotations

import logging

from app.config import get_settings
from app.core.errors import ModelUnavailableError
from app.services.forecasting.base import Forecaster
from app.services.forecasting.chronos import ChronosForecaster
from app.services.forecasting.chronos2 import Chronos2Forecaster
from app.services.forecasting.statistical import (
    SeasonalNaiveForecaster,
    build_statistical_forecasters,
)

LOG = logging.getLogger(__name__)

# Chronos-2 leads because it is the only model that can use the weather, holiday
# and sentiment covariates. Chronos-Bolt stays as the univariate comparison.
DEFAULT_MODEL = "chronos-2"
# Tried in order when the requested model is unavailable. Seasonal-naive is last
# because it always works.
FALLBACK_ORDER = (
    "chronos-2", "chronos-bolt", "auto-ets", "auto-arima", "theta", "seasonal-naive",
)


def build_registry() -> dict[str, Forecaster]:
    settings = get_settings()
    forecasters: list[Forecaster] = []
    if settings.chronos2_enabled:
        forecasters.append(Chronos2Forecaster())
    if settings.chronos_enabled:
        forecasters.append(ChronosForecaster())
    forecasters.extend(build_statistical_forecasters())
    return {f.name: f for f in forecasters}


def list_models() -> list[dict[str, object]]:
    return [
        {**forecaster.describe(), "available": forecaster.available}
        for forecaster in build_registry().values()
    ]


def get_forecaster(name: str | None = None) -> tuple[Forecaster, str | None]:
    """Resolve a model name to a usable forecaster.

    Returns ``(forecaster, fell_back_from)``. ``fell_back_from`` is the originally
    requested name when substitution occurred, so the API can tell the user which
    model actually served their request instead of quietly swapping it.
    """
    registry = build_registry()
    requested = name or get_settings().default_model or DEFAULT_MODEL

    if requested not in registry:
        raise ModelUnavailableError(
            f"Unknown model '{requested}'. Available: {', '.join(sorted(registry))}.",
            requested=requested, available=sorted(registry),
        )

    forecaster = registry[requested]
    if forecaster.available:
        return forecaster, None

    for candidate_name in FALLBACK_ORDER:
        candidate = registry.get(candidate_name)
        if candidate is not None and candidate_name != requested and candidate.available:
            LOG.warning("Model '%s' unavailable; falling back to '%s'", requested, candidate_name)
            return candidate, requested

    LOG.warning("All registered models unavailable; using built-in seasonal naive")
    return SeasonalNaiveForecaster(), requested
