"""Covariate plumbing: alignment, the past/future split, and honest selection.

The network-dependent providers are marked; everything here that matters
structurally runs offline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.enrichment.base import CovariateFrame, CovariateSpec, Location
from app.services.enrichment.calendar import CalendarProvider
from app.services.enrichment.sentiment import SentimentProvider

LONDON = Location("London", 51.51, -0.13, "GB", "Europe/London")


@pytest.fixture
def index() -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=120, freq="D")


# ── calendar (offline, deterministic) ─────────────────────────────────────────

def test_calendar_emits_every_declared_column(index):
    provider = CalendarProvider()
    frame = provider.fetch(index, LONDON)
    for spec in provider.specs():
        assert spec.name in frame.columns, spec.name
    assert len(frame) == len(index)


def test_cyclical_encoding_keeps_adjacent_months_adjacent():
    """December and January must be near each other, which raw integers get wrong."""
    provider = CalendarProvider()
    frame = provider.fetch(pd.DatetimeIndex(["2024-12-15", "2024-01-15", "2024-06-15"]), LONDON)

    def point(i):
        return np.array([frame["month_sin"].iloc[i], frame["month_cos"].iloc[i]])

    dec_to_jan = np.linalg.norm(point(0) - point(1))
    dec_to_jun = np.linalg.norm(point(0) - point(2))
    assert dec_to_jan < dec_to_jun


def test_weekend_flag_matches_the_calendar(index):
    frame = CalendarProvider().fetch(index, LONDON)
    assert (frame["is_weekend"] == (index.dayofweek >= 5).astype(float)).all()


def test_payday_distance_is_zero_on_paydays():
    frame = CalendarProvider().fetch(
        pd.DatetimeIndex(["2024-03-01", "2024-03-07", "2024-03-20"]), LONDON
    )
    assert frame["days_from_payday"].iloc[0] == 0
    assert frame["days_from_payday"].iloc[1] == 0
    assert frame["days_from_payday"].iloc[2] > 0


# ── sentiment (offline) ───────────────────────────────────────────────────────

def test_sentiment_is_past_only():
    """Tomorrow's sentiment is not knowable today; marking it known-future would leak."""
    for spec in SentimentProvider({"2024-01-01": 0.5}).specs():
        assert spec.known_future is False


def test_non_overlapping_sentiment_is_excluded_not_zero_filled(index):
    """The bundled dataset ends in 2011; today's social data cannot apply to it."""
    provider = SentimentProvider({"2026-08-01": 0.4, "2026-08-02": -0.2})
    frame = provider.fetch(index, LONDON)

    assert frame.empty or frame.shape[1] == 0, "must not emit a column of invented zeros"
    assert any("does not overlap" in w for w in provider.warnings())


def test_overlapping_sentiment_is_used(index):
    days = {d.strftime("%Y-%m-%d"): 0.5 for d in index[:40]}
    frame = SentimentProvider(days).fetch(index, LONDON)

    assert "sentiment_index" in frame.columns
    assert frame["sentiment_index"].iloc[:40].mean() == pytest.approx(0.5)


# ── CovariateFrame contract ───────────────────────────────────────────────────

def _frame() -> CovariateFrame:
    past = pd.date_range("2024-01-01", periods=30, freq="D")
    future = pd.date_range("2024-01-31", periods=7, freq="D")
    return CovariateFrame(
        past=pd.DataFrame(
            {"is_holiday": 0.0, "temp_mean": 10.0, "sentiment_index": 0.1}, index=past
        ),
        future=pd.DataFrame({"is_holiday": 0.0, "temp_mean": 10.0}, index=future),
        specs=[
            CovariateSpec("is_holiday", "holiday", True),
            CovariateSpec("temp_mean", "weather", True),
            CovariateSpec("sentiment_index", "sentiment", False),
        ],
    )


def test_known_future_excludes_past_only_columns():
    frame = _frame()
    assert set(frame.known_future_columns()) == {"is_holiday", "temp_mean"}
    assert "sentiment_index" not in frame.future.columns


def test_only_and_without_are_complementary():
    frame = _frame()
    assert frame.only(["holiday"]).column_names == ["is_holiday"]
    assert "temp_mean" not in frame.without("weather").column_names
    assert frame.groups == ["holiday", "weather", "sentiment"]


def test_unknown_group_is_rejected():
    with pytest.raises(ValueError, match="unknown covariate group"):
        CovariateSpec("x", "astrology", True)


# ── selection ─────────────────────────────────────────────────────────────────

def test_selection_reports_unavailable_for_univariate_models(series):
    from app.services.forecasting.covariate_selection import select_covariates
    from app.services.forecasting.statistical import SeasonalNaiveForecaster

    selection = select_covariates(
        SeasonalNaiveForecaster(), series, 14, lambda a, b: _frame(),
        available_groups=["holiday"],
    )
    assert selection.method == "unavailable"
    assert selection.selected == []


def test_selection_skips_when_series_too_short():
    from app.services.forecasting.chronos2 import Chronos2Forecaster
    from app.services.forecasting.covariate_selection import select_covariates

    short = pd.Series(
        np.arange(40, dtype="float64"), index=pd.date_range("2024-01-01", periods=40, freq="D")
    )
    selection = select_covariates(
        Chronos2Forecaster(), short, 30, lambda a, b: _frame(),
        available_groups=["holiday"],
    )
    assert selection.method == "skipped"
    assert "too short" in selection.note


# ── geo ───────────────────────────────────────────────────────────────────────

def test_indian_state_holidays_differ_from_national():
    """Karnataka and Maharashtra do not observe the same calendar."""
    from app.services.enrichment.holidays import HolidayProvider

    index = pd.date_range("2026-01-01", periods=365, freq="D")
    ka = HolidayProvider().fetch(
        index, Location("Bangalore", 12.97, 77.59, "IN", subdivision="KA")
    )["is_holiday"].sum()
    mh = HolidayProvider().fetch(
        index, Location("Mumbai", 19.08, 72.88, "IN", subdivision="MH")
    )["is_holiday"].sum()
    assert ka > 0 and mh > 0
    assert ka != mh


def test_unknown_country_degrades_without_raising():
    from app.services.enrichment.holidays import HolidayProvider

    provider = HolidayProvider()
    index = pd.date_range("2026-01-01", periods=30, freq="D")
    frame = provider.fetch(index, Location("Nowhere", 0.0, 0.0, "ZZ"))
    assert frame.empty or frame.shape[1] == 0
    assert provider.warnings()


def test_known_regions_resolve_offline():
    from app.services.enrichment import geo

    uk = geo.resolve("United Kingdom")
    assert uk.country_code == "GB" and uk.resolved_by == "lookup"

    blr = geo.resolve("Bangalore")
    assert blr.country_code == "IN" and blr.latitude == pytest.approx(12.97, abs=0.1)
    assert blr.subdivision == "KA", "Indian regions should carry their state code"


def test_missing_region_falls_back_to_a_named_default():
    from app.services.enrichment import geo

    location = geo.resolve(None)
    assert location.resolved_by == "default"
    assert "default" in location.name


def test_dominant_region_uses_volume_not_row_order():
    from app.services.enrichment import geo

    frame = pd.DataFrame({
        "region": ["Small", "Big", "Big"],
        "units": [1.0, 500.0, 500.0],
    })
    assert geo.dominant_region(frame) == "Big"


def test_holidays_cover_india_offline():
    """The reason Nager.Date was dropped: it has no Indian calendar at all."""
    from app.services.enrichment.holidays import HolidayProvider

    index = pd.date_range("2026-01-01", periods=365, freq="D")
    frame = HolidayProvider().fetch(
        index, Location("Bangalore", 12.97, 77.59, "IN", "Asia/Kolkata", subdivision="KA")
    )

    assert not frame.empty
    assert frame["is_holiday"].sum() >= 15, "India has ~20 holidays a year in Karnataka"
    assert frame["days_to_next_holiday"].max() <= 60
    # Diwali must be recognised as a major retail festival, not just a day off.
    assert (frame["days_to_major_festival"] == 0).sum() > 0


@pytest.mark.slow
@pytest.mark.network
def test_weather_marks_climatology_beyond_the_forecast_horizon():
    from app.services.enrichment.weather import WeatherProvider

    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    index = pd.date_range(today - pd.Timedelta(days=60), periods=150, freq="D")
    provider = WeatherProvider()
    frame = provider.fetch(index, LONDON)

    assert "weather_is_forecast" in frame.columns
    # Days far beyond the 16-day horizon must be flagged as climatology, not forecast.
    assert frame["weather_is_forecast"].iloc[-1] == 0.0
    assert any("climatology" in w for w in provider.warnings())
