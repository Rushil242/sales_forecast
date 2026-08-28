"""Assemble every provider's output into one aligned :class:`CovariateFrame`.

Responsibilities kept in one place so no caller has to remember them:

* Build the union index -- history plus the forecast horizon -- in one pass, so
  providers make a single request covering both rather than one each.
* Split the result into ``past`` (all columns, history dates) and ``future``
  (known-future columns only, horizon dates). That split is what stops a past-only
  covariate leaking into the horizon.
* Drop any column that is entirely missing or constant. A constant column carries no
  information and only slows the model down.
* Cache aggressively: the weather archive for 2010 will never change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import pandas as pd

from app.config import get_settings
from app.services.enrichment.base import CovariateFrame, CovariateSpec, Location
from app.services.enrichment.calendar import CalendarProvider
from app.services.enrichment.holidays import HolidayProvider
from app.services.enrichment.sentiment import SentimentProvider
from app.services.enrichment.weather import WeatherProvider

LOG = logging.getLogger(__name__)


def _cache_dir() -> Path:
    directory = get_settings().data_dir / "cache" / "enrichment"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cache_key(provider: str, index: pd.DatetimeIndex, location: Location) -> str:
    payload = json.dumps({
        "provider": provider,
        "start": index.min().isoformat(),
        "end": index.max().isoformat(),
        "n": len(index),
        "lat": round(location.latitude, 3),
        "lon": round(location.longitude, 3),
        "cc": location.country_code,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _load_cached(provider: str, index: pd.DatetimeIndex, location: Location) -> pd.DataFrame | None:
    path = _cache_dir() / f"{provider}-{_cache_key(provider, index, location)}.parquet"
    if not path.exists():
        return None
    # Weather/holiday history is immutable, but a run that touched *today* may have
    # cached a provisional value, so entries expire after a day.
    if time.time() - path.stat().st_mtime > 86_400:
        return None
    try:
        frame = pd.read_parquet(path)
        LOG.debug("Enrichment cache hit for %s", provider)
        return frame
    except Exception:
        return None


def _store_cached(provider: str, index: pd.DatetimeIndex, location: Location,
                  frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    path = _cache_dir() / f"{provider}-{_cache_key(provider, index, location)}.parquet"
    try:
        frame.to_parquet(path)
    except Exception as exc:
        LOG.debug("Could not cache %s: %s", provider, exc)


def build_covariates(
    history: pd.DatetimeIndex,
    horizon: pd.DatetimeIndex,
    location: Location,
    *,
    sentiment: dict[str, float] | None = None,
    groups: list[str] | None = None,
    use_cache: bool = True,
) -> CovariateFrame:
    """Build covariates spanning ``history`` then ``horizon``.

    ``groups`` restricts which providers run; ``None`` means all available.
    """
    settings = get_settings()
    requested = set(groups or ["calendar", "holiday", "weather", "sentiment"])

    providers = []
    if "calendar" in requested:
        providers.append(CalendarProvider())
    if "holiday" in requested and settings.enrichment_holidays_enabled:
        providers.append(HolidayProvider(timeout=settings.enrichment_timeout))
    if "weather" in requested and settings.enrichment_weather_enabled:
        providers.append(WeatherProvider(timeout=settings.enrichment_timeout))
    if "sentiment" in requested and sentiment:
        providers.append(SentimentProvider(sentiment))

    full_index = history.append(horizon)
    frames: list[pd.DataFrame] = []
    specs: list[CovariateSpec] = []
    warnings: list[str] = []

    for provider in providers:
        if not provider.available():
            warnings.append(f"{provider.name}: {provider.unavailable_reason()}")
            continue

        started = time.perf_counter()
        frame = None
        if use_cache and provider.group != "sentiment":
            frame = _load_cached(provider.name, full_index, location)

        if frame is None:
            try:
                frame = provider.fetch(full_index, location)
            except Exception as exc:
                LOG.warning("Enrichment provider %s failed: %s", provider.name, exc)
                warnings.append(f"{provider.name}: unavailable ({exc}).")
                continue
            if use_cache and provider.group != "sentiment":
                _store_cached(provider.name, full_index, location, frame)

        warnings.extend(provider.warnings())

        if frame is None or frame.empty:
            continue

        # Keep only the columns the provider actually delivered and that carry signal.
        emitted = {spec.name for spec in provider.specs()}
        usable = []
        for column in frame.columns:
            if column not in emitted:
                continue
            series = frame[column]
            if series.isna().all():
                continue
            if series.nunique(dropna=True) <= 1:
                LOG.debug("Dropping constant covariate %s", column)
                continue
            usable.append(column)

        if not usable:
            continue

        frames.append(frame[usable])
        specs.extend([s for s in provider.specs() if s.name in usable])
        LOG.info(
            "Enrichment %s: %d columns in %d ms",
            provider.name, len(usable), int((time.perf_counter() - started) * 1000),
        )

    if not frames:
        return CovariateFrame(
            past=pd.DataFrame(index=history), future=pd.DataFrame(index=horizon),
            specs=[], warnings=warnings,
        )

    combined = pd.concat(frames, axis=1)
    combined = combined.loc[:, ~combined.columns.duplicated()]
    combined = combined.ffill().bfill().fillna(0.0)

    known_future = [s.name for s in specs if s.known_future and s.name in combined.columns]

    return CovariateFrame(
        past=combined.loc[combined.index.isin(history)],
        future=combined.loc[combined.index.isin(horizon), known_future],
        specs=specs,
        warnings=warnings,
    )


def build_for_series(
    series: pd.Series,
    horizon: int,
    region: str | None,
    *,
    sentiment: dict[str, float] | None = None,
    groups: list[str] | None = None,
) -> tuple[CovariateFrame, Location]:
    """Convenience wrapper: derive the horizon index from a series and build."""
    from app.services.enrichment import geo

    location = geo.resolve(region)
    future_index = pd.date_range(
        series.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D"
    )
    frame = build_covariates(
        pd.DatetimeIndex(series.index), future_index, location,
        sentiment=sentiment, groups=groups,
    )
    return frame, location
