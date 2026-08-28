"""Weather covariates from Open-Meteo.

Free, unlimited for non-commercial use, and **no API key at all** -- which is why it
was chosen over OpenWeatherMap or WeatherAPI, both of which gate their historical
archive behind a paid tier.

The honest problem with weather as a forecast covariate
-------------------------------------------------------
Weather is only *known-future* for about 16 days. A 30-day sales horizon runs past
that, and a 180-day horizon runs far past it. Three ways to handle the tail:

1. Pretend the forecast extends -- silently wrong.
2. Drop weather entirely for long horizons -- throws away real signal in the first
   fortnight.
3. Use the meteorological forecast where it exists and **day-of-year climatology**
   (the historical average for that calendar day at that location) beyond it.

This module does (3), and emits a companion ``weather_is_forecast`` flag so the model
and the user can both see which days are real forecast and which are long-run
average. The response carries a warning naming the cut-over date.
"""

from __future__ import annotations

import logging

import httpx
import pandas as pd

from app.services.enrichment.base import CovariateSpec, EnrichmentProvider, Location

LOG = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo's free forecast reaches 16 days; the archive lags real time by ~5 days.
FORECAST_HORIZON_DAYS = 16
ARCHIVE_LAG_DAYS = 5

DAILY_VARIABLES = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "precipitation_sum",
    "wind_speed_10m_max",
]

_COLUMN_MAP = {
    "temperature_2m_mean": "temp_mean",
    "temperature_2m_max": "temp_max",
    "precipitation_sum": "precipitation",
    "wind_speed_10m_max": "wind_max",
}


class WeatherProvider(EnrichmentProvider):
    name = "weather"
    group = "weather"

    def __init__(self, timeout: float = 25.0) -> None:
        self.timeout = timeout
        self._warnings: list[str] = []

    def specs(self) -> list[CovariateSpec]:
        return [
            CovariateSpec("temp_mean", "weather", True, "numeric",
                          "Daily mean temperature (°C)"),
            CovariateSpec("temp_max", "weather", True, "numeric",
                          "Daily maximum temperature (°C)"),
            CovariateSpec("precipitation", "weather", True, "numeric",
                          "Daily precipitation total (mm)"),
            CovariateSpec("wind_max", "weather", True, "numeric",
                          "Daily maximum wind speed (km/h)"),
            CovariateSpec("weather_is_forecast", "weather", True, "numeric",
                          "1 where the value is a real forecast, 0 where it is "
                          "day-of-year climatology"),
        ]

    # ── fetching ─────────────────────────────────────────────────────────────

    def _request(self, url: str, params: dict) -> pd.DataFrame:
        response = httpx.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        daily = response.json().get("daily") or {}
        if not daily.get("time"):
            return pd.DataFrame()

        frame = pd.DataFrame(daily)
        frame["time"] = pd.to_datetime(frame["time"])
        frame = frame.set_index("time").rename(columns=_COLUMN_MAP)
        return frame[[c for c in _COLUMN_MAP.values() if c in frame.columns]]

    def _archive(self, start, end, location: Location) -> pd.DataFrame:
        return self._request(ARCHIVE_URL, {
            "latitude": location.latitude, "longitude": location.longitude,
            "start_date": start.strftime("%Y-%m-%d"), "end_date": end.strftime("%Y-%m-%d"),
            "daily": ",".join(DAILY_VARIABLES), "timezone": "UTC",
        })

    def _forecast(self, location: Location, days: int) -> pd.DataFrame:
        return self._request(FORECAST_URL, {
            "latitude": location.latitude, "longitude": location.longitude,
            "daily": ",".join(DAILY_VARIABLES), "timezone": "UTC",
            "forecast_days": min(days, FORECAST_HORIZON_DAYS),
        })

    @staticmethod
    def _climatology(history: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
        """Day-of-year averages from whatever history we already hold.

        Explicitly *not* a forecast. Sales data spanning multiple years gives a
        genuine seasonal profile; a single year gives a weak one, which is why the
        caller warns when history is short.
        """
        if history.empty:
            return pd.DataFrame(index=index)
        by_doy = history.groupby(history.index.dayofyear).mean(numeric_only=True)
        rows = by_doy.reindex(index.dayofyear)
        rows.index = index
        return rows.ffill().bfill()

    def fetch(self, index: pd.DatetimeIndex, location: Location) -> pd.DataFrame:
        """Weather over ``index``, blending archive, forecast and climatology."""
        self._warnings = []
        if len(index) == 0:
            return pd.DataFrame()

        today = pd.Timestamp.utcnow().normalize().tz_localize(None)
        archive_end = today - pd.Timedelta(days=ARCHIVE_LAG_DAYS)
        start, end = index.min(), index.max()

        archive = pd.DataFrame()
        if start <= archive_end:
            try:
                archive = self._archive(start, min(end, archive_end), location)
            except Exception as exc:
                LOG.warning("Open-Meteo archive failed for %s: %s", location, exc)
                self._warnings.append(f"Historical weather unavailable ({exc}).")

        forecast = pd.DataFrame()
        if end > archive_end:
            try:
                forecast = self._forecast(location, (end - today).days + 1)
            except Exception as exc:
                LOG.warning("Open-Meteo forecast failed for %s: %s", location, exc)
                self._warnings.append(f"Weather forecast unavailable ({exc}).")

        observed = pd.concat([archive, forecast])
        observed = observed[~observed.index.duplicated(keep="last")].sort_index()

        if observed.empty:
            self._warnings.append(
                "No weather data could be retrieved; the forecast proceeds without it."
            )
            return pd.DataFrame(index=index)

        aligned = observed.reindex(index)
        real = aligned.notna().all(axis=1)

        # Fill everything the archive and forecast could not cover.
        missing = ~real
        if missing.any():
            climate = self._climatology(observed, index[missing])
            for column in aligned.columns:
                if column in climate.columns:
                    aligned.loc[missing, column] = climate[column].to_numpy()

            beyond = index[missing]
            if (beyond > today).any():
                cutover = beyond[beyond > today].min()
                self._warnings.append(
                    f"Weather beyond {cutover.date()} is day-of-year climatology, not a "
                    f"forecast — Open-Meteo forecasts {FORECAST_HORIZON_DAYS} days ahead."
                )

        aligned["weather_is_forecast"] = real.astype(float)
        return aligned.ffill().bfill()

    def warnings(self) -> list[str]:
        return list(self._warnings)
