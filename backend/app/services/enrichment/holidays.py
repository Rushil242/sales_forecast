"""Public-holiday covariates.

Why not Nager.Date
------------------
Nager.Date is the API most "free holiday API" listicles recommend, and it was the
first choice here. Testing it against our actual target market disqualified it:

    GET /api/v3/PublicHolidays/2024/GB  ->  200, 9 holidays
    GET /api/v3/PublicHolidays/2024/US  ->  200, 12 holidays
    GET /api/v3/PublicHolidays/2024/IN  ->  204 No Content

India is simply not in its 204-country list. For a product aimed at Indian
retailers, a holiday source that cannot name Diwali is not a holiday source.

``python-holidays`` instead
---------------------------
Offline, MIT-licensed, no key, no rate limit, no network call at all -- and it
covers India properly: 18 national holidays for 2026 including Diwali, Holi and
Dussehra, plus all 36 state subdivisions (Karnataka adds two more on top of the
national set). It also covers GB back to 2011 for the bundled dataset.

Retail-shaped features
----------------------
A holiday's effect on demand is not confined to the day itself, so four columns are
emitted rather than one. ``days_to_major_festival`` is the important one for Indian
retail: Diwali shopping happens in the fortnight *before* Diwali, not on the day.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.services.enrichment.base import CovariateSpec, EnrichmentProvider, Location

LOG = logging.getLogger(__name__)

# Beyond this the "next holiday" distance stops being informative and just adds noise.
MAX_DAYS_AHEAD = 60

# Festivals that genuinely move retail volume, as opposed to public holidays that
# merely close offices. Matched case-insensitively against the holiday name.
MAJOR_FESTIVALS = (
    "diwali", "deepavali", "christmas", "eid", "id-ul-fitr", "holi", "dussehra",
    "navratri", "onam", "pongal", "raksha", "ganesh", "durga", "thanksgiving",
    "new year", "good friday", "easter",
)


def _is_major(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in MAJOR_FESTIVALS)


def _days_until(index: pd.DatetimeIndex, targets: pd.DatetimeIndex) -> list[float]:
    """Days from each date in ``index`` to the next date in ``targets``, capped."""
    if len(targets) == 0:
        return [float(MAX_DAYS_AHEAD)] * len(index)

    positions = targets.searchsorted(index, side="left")
    distances: list[float] = []
    for i, position in enumerate(positions):
        if position >= len(targets):
            distances.append(float(MAX_DAYS_AHEAD))
        else:
            distances.append(float(min((targets[position] - index[i]).days, MAX_DAYS_AHEAD)))
    return distances


class HolidayProvider(EnrichmentProvider):
    name = "holidays"
    group = "holiday"

    def __init__(self, timeout: float = 15.0) -> None:
        # Signature kept for interface compatibility; nothing here touches the network.
        self.timeout = timeout
        self._warnings: list[str] = []

    def available(self) -> bool:
        try:
            import holidays  # noqa: F401
        except ImportError:
            return False
        return True

    def unavailable_reason(self) -> str:
        return "The 'holidays' package is not installed."

    def specs(self) -> list[CovariateSpec]:
        return [
            CovariateSpec("is_holiday", "holiday", True, "numeric",
                          "1 on a public holiday in the series' country or state"),
            CovariateSpec("days_to_next_holiday", "holiday", True, "numeric",
                          f"Days until the next public holiday, capped at {MAX_DAYS_AHEAD}"),
            CovariateSpec("is_long_weekend", "holiday", True, "numeric",
                          "1 when the holiday bridges or falls on a weekend"),
            CovariateSpec("days_to_major_festival", "holiday", True, "numeric",
                          "Days until the next major retail festival (Diwali, Christmas, "
                          f"Eid...), capped at {MAX_DAYS_AHEAD} - the run-up is when "
                          "buying actually happens"),
        ]

    def _calendar(self, years: range, location: Location) -> dict:
        """Resolve the holiday calendar, narrowing to a state where we know one."""
        import holidays

        country = (location.country_code or "GB").upper()
        subdivision = getattr(location, "subdivision", None)

        try:
            if subdivision:
                try:
                    return dict(holidays.country_holidays(
                        country, subdiv=subdivision, years=list(years)
                    ))
                except (KeyError, NotImplementedError):
                    LOG.info(
                        "Subdivision %s not supported for %s; using the national calendar",
                        subdivision, country,
                    )
            return dict(holidays.country_holidays(country, years=list(years)))
        except (KeyError, NotImplementedError):
            self._warnings.append(
                f"No holiday calendar exists for country code {country}; the forecast "
                "proceeds without holiday signals."
            )
            return {}
        except Exception as exc:
            self._warnings.append(f"Holiday calendar unavailable ({exc}).")
            return {}

    def fetch(self, index: pd.DatetimeIndex, location: Location) -> pd.DataFrame:
        self._warnings = []
        if len(index) == 0:
            return pd.DataFrame()

        # One year either side so run-up and look-back work at the boundaries.
        years = range(index.min().year - 1, index.max().year + 2)
        calendar = self._calendar(years, location)
        if not calendar:
            return pd.DataFrame(index=index)

        all_dates = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in calendar))
        major_dates = pd.DatetimeIndex(sorted(
            pd.Timestamp(d) for d, name in calendar.items() if _is_major(str(name))
        ))

        frame = pd.DataFrame(index=index)
        frame["is_holiday"] = index.isin(all_dates).astype(float)
        frame["days_to_next_holiday"] = _days_until(index, all_dates)
        frame["days_to_major_festival"] = _days_until(index, major_dates)

        # Mon/Fri holidays bridge into a weekend; Sat/Sun ones already sit on one.
        long_weekend = pd.DatetimeIndex([d for d in all_dates if d.dayofweek in (0, 4, 5, 6)])
        frame["is_long_weekend"] = index.isin(long_weekend).astype(float)

        subdivision = getattr(location, "subdivision", None)
        LOG.info(
            "Holidays: %d dates (%d major) for %s%s across %d-%d",
            len(all_dates), len(major_dates), location.country_code,
            f"/{subdivision}" if subdivision else "",
            index.min().year, index.max().year,
        )
        return frame

    def warnings(self) -> list[str]:
        return list(self._warnings)
