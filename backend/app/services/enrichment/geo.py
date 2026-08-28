"""Resolve a dataset's region label to coordinates and a holiday calendar.

Regions in real retail data are whatever the source system happened to store --
"United Kingdom", "Bangalore", "Maharashtra", "EIRE". Rather than demand a fixed
vocabulary, this resolves in three steps:

1. A built-in table covering the countries in the bundled dataset and the Indian
   metros our target users actually trade in. Instant, offline, no request.
2. Open-Meteo's geocoding API for anything else -- free, no key, no quota.
3. A documented default, so a forecast never fails just because a region is unknown.
"""

from __future__ import annotations

import logging

import httpx

from app.services.enrichment.base import Location

LOG = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Indian metros: the regions our intended users trade in, and the four the bundled
# Zara sample uses. Values are (lat, lon, ISO 3166-2 state). The state matters:
# Karnataka observes
# holidays Maharashtra does not, and retail demand follows the state calendar.
_INDIA = {
    "bangalore": (12.97, 77.59, "KA"),
    "bengaluru": (12.97, 77.59, "KA"),
    "karnataka": (12.97, 77.59, "KA"),
    "mumbai": (19.08, 72.88, "MH"),
    "pune": (18.52, 73.86, "MH"),
    "maharashtra": (19.08, 72.88, "MH"),
    "delhi": (28.61, 77.21, "DL"),
    "new delhi": (28.61, 77.21, "DL"),
    "hyderabad": (17.39, 78.49, "TS"),
    "telangana": (17.39, 78.49, "TS"),
    "chennai": (13.08, 80.27, "TN"),
    "tamil nadu": (13.08, 80.27, "TN"),
    "kolkata": (22.57, 88.36, "WB"),
    "west bengal": (22.57, 88.36, "WB"),
    "ahmedabad": (23.02, 72.57, "GJ"),
    "gujarat": (23.02, 72.57, "GJ"),
    "jaipur": (26.91, 75.79, "RJ"),
    "rajasthan": (26.91, 75.79, "RJ"),
    "kochi": (9.93, 76.27, "KL"),
    "kerala": (9.93, 76.27, "KL"),
    "lucknow": (26.85, 80.95, "UP"),
    "india": (20.59, 78.96, None),
}

# Countries present in the bundled UCI dataset, plus common trading partners.
_COUNTRIES = {
    "united kingdom": (51.51, -0.13, "GB", "Europe/London"),
    "uk": (51.51, -0.13, "GB", "Europe/London"),
    "eire": (53.35, -6.26, "IE", "Europe/Dublin"),
    "ireland": (53.35, -6.26, "IE", "Europe/Dublin"),
    "netherlands": (52.37, 4.90, "NL", "Europe/Amsterdam"),
    "france": (48.86, 2.35, "FR", "Europe/Paris"),
    "germany": (52.52, 13.40, "DE", "Europe/Berlin"),
    "spain": (40.42, -3.70, "ES", "Europe/Madrid"),
    "portugal": (38.72, -9.14, "PT", "Europe/Lisbon"),
    "belgium": (50.85, 4.35, "BE", "Europe/Brussels"),
    "switzerland": (47.38, 8.54, "CH", "Europe/Zurich"),
    "italy": (41.90, 12.50, "IT", "Europe/Rome"),
    "sweden": (59.33, 18.07, "SE", "Europe/Stockholm"),
    "norway": (59.91, 10.75, "NO", "Europe/Oslo"),
    "denmark": (55.68, 12.57, "DK", "Europe/Copenhagen"),
    "finland": (60.17, 24.94, "FI", "Europe/Helsinki"),
    "poland": (52.23, 21.01, "PL", "Europe/Warsaw"),
    "austria": (48.21, 16.37, "AT", "Europe/Vienna"),
    "australia": (-33.87, 151.21, "AU", "Australia/Sydney"),
    "usa": (40.71, -74.01, "US", "America/New_York"),
    "united states": (40.71, -74.01, "US", "America/New_York"),
    "canada": (43.65, -79.38, "CA", "America/Toronto"),
    "japan": (35.68, 139.69, "JP", "Asia/Tokyo"),
    "singapore": (1.35, 103.82, "SG", "Asia/Singapore"),
    "hong kong": (22.32, 114.17, "HK", "Asia/Hong_Kong"),
    "uae": (25.20, 55.27, "AE", "Asia/Dubai"),
}

# Used when a dataset has no region column at all. Named explicitly so the response
# can say the location was assumed rather than resolved.
DEFAULT_LOCATION = Location(
    name="London (default)", latitude=51.51, longitude=-0.13,
    country_code="GB", timezone="Europe/London", resolved_by="default",
)

_cache: dict[str, Location] = {}


def _geocode(region: str, timeout: float) -> Location | None:
    """Look the region up with Open-Meteo's free geocoding API."""
    try:
        response = httpx.get(
            GEOCODE_URL,
            params={"name": region, "count": 1, "language": "en", "format": "json"},
            timeout=timeout,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
    except Exception as exc:
        LOG.warning("Geocoding failed for %r: %s", region, exc)
        return None

    if not results:
        return None

    hit = results[0]
    return Location(
        name=hit.get("name", region),
        latitude=float(hit["latitude"]),
        longitude=float(hit["longitude"]),
        country_code=(hit.get("country_code") or "GB").upper(),
        timezone=hit.get("timezone", "UTC"),
        resolved_by="geocoded",
    )


def resolve(region: str | None, *, timeout: float = 10.0) -> Location:
    """Resolve a region label to a :class:`Location`. Never raises."""
    if not region or not str(region).strip():
        return DEFAULT_LOCATION

    key = str(region).strip().lower()
    if key in _cache:
        return _cache[key]

    if key in _INDIA:
        latitude, longitude, subdivision = _INDIA[key]
        location = Location(
            name=str(region).strip().title(), latitude=latitude, longitude=longitude,
            country_code="IN", timezone="Asia/Kolkata", resolved_by="lookup",
            subdivision=subdivision,
        )
    elif key in _COUNTRIES:
        latitude, longitude, country_code, timezone = _COUNTRIES[key]
        location = Location(
            name=str(region).strip(), latitude=latitude, longitude=longitude,
            country_code=country_code, timezone=timezone, resolved_by="lookup",
        )
    else:
        location = _geocode(str(region).strip(), timeout) or DEFAULT_LOCATION
        if location is DEFAULT_LOCATION:
            LOG.info("Region %r could not be resolved; using %s", region, DEFAULT_LOCATION.name)

    _cache[key] = location
    return location


def dominant_region(frame) -> str | None:
    """The region responsible for most of a dataset's volume.

    A single forecast covers one series, so one location has to stand for it. Using
    the highest-volume region rather than the first row keeps the weather relevant:
    the bundled dataset is 94% United Kingdom.
    """
    if "region" not in getattr(frame, "columns", []):
        return None
    if "units" in frame.columns:
        totals = frame.groupby("region")["units"].sum()
    else:
        totals = frame["region"].value_counts()
    return str(totals.idxmax()) if len(totals) else None
