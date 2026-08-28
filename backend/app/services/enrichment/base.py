"""Covariate contracts shared by every enrichment provider.

A covariate is an external signal aligned to the sales calendar. Two kinds matter,
and confusing them is the classic way to leak the future into a forecast:

**Known-future**  Its value on a future date is genuinely knowable today. Holidays and
                  calendar features are the honest examples -- Diwali's date next year
                  is not a prediction.
**Past-only**     Only observable up to today. Social sentiment is the obvious case;
                  so is weather beyond the meteorological forecast horizon.

Chronos-2 distinguishes the two by presence: a column supplied in the context frame
but absent from the future frame is treated as past-only. :class:`CovariateFrame`
therefore keeps the two frames separate rather than trusting callers to remember.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace

import pandas as pd

LOG = logging.getLogger(__name__)

# Groups exist so a covariate's contribution can be measured by removing the whole
# group at once (leave-one-group-out attribution). Removing a single column of a
# correlated pair tells you very little.
GROUPS = ("calendar", "holiday", "weather", "sentiment")


@dataclass(frozen=True)
class CovariateSpec:
    """Describes one covariate column, for attribution and for the UI."""

    name: str
    group: str
    known_future: bool
    kind: str = "numeric"  # numeric | categorical
    description: str = ""

    def __post_init__(self) -> None:
        if self.group not in GROUPS:
            raise ValueError(f"unknown covariate group {self.group!r}; expected one of {GROUPS}")


@dataclass
class CovariateFrame:
    """Aligned covariates for one series, split by availability.

    ``past`` is indexed by every date in the training history. ``future`` is indexed by
    every date in the horizon and holds only the known-future columns.
    """

    past: pd.DataFrame
    future: pd.DataFrame
    specs: list[CovariateSpec] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.past.empty or not self.specs

    @property
    def column_names(self) -> list[str]:
        return [spec.name for spec in self.specs]

    @property
    def groups(self) -> list[str]:
        """Groups actually present, in the canonical order."""
        present = {spec.group for spec in self.specs}
        return [group for group in GROUPS if group in present]

    def known_future_columns(self) -> list[str]:
        return [spec.name for spec in self.specs if spec.known_future]

    def describe(self) -> list[dict]:
        return [
            {
                "name": s.name, "group": s.group, "known_future": s.known_future,
                "kind": s.kind, "description": s.description,
            }
            for s in self.specs
        ]

    def without(self, group: str) -> CovariateFrame:
        """Drop one whole group. Used for leave-one-group-out attribution."""
        keep = [spec for spec in self.specs if spec.group != group]
        names = [spec.name for spec in keep]
        return replace(
            self,
            past=self.past[[c for c in names if c in self.past.columns]],
            future=self.future[[c for c in names if c in self.future.columns]],
            specs=keep,
        )

    def only(self, groups: list[str]) -> CovariateFrame:
        keep = [spec for spec in self.specs if spec.group in groups]
        names = [spec.name for spec in keep]
        return replace(
            self,
            past=self.past[[c for c in names if c in self.past.columns]],
            future=self.future[[c for c in names if c in self.future.columns]],
            specs=keep,
        )


class EnrichmentProvider(ABC):
    """A source of covariate columns for a given date range and place."""

    name: str = "provider"
    group: str = "calendar"

    @abstractmethod
    def specs(self) -> list[CovariateSpec]:
        """The columns this provider emits, whether or not the fetch succeeds."""

    @abstractmethod
    def fetch(self, index: pd.DatetimeIndex, location: Location) -> pd.DataFrame:
        """Return a frame indexed by ``index``. Missing values are permitted."""

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""


@dataclass(frozen=True)
class Location:
    """Where a series' demand happens. Drives weather and holiday lookups."""

    name: str
    latitude: float
    longitude: float
    country_code: str  # ISO 3166-1 alpha-2, for the holiday calendar
    timezone: str = "UTC"
    resolved_by: str = "lookup"  # lookup | geocoded | default
    # Optional ISO 3166-2 subdivision. Indian states matter: Karnataka observes
    # holidays Maharashtra does not, and retail follows the state calendar.
    subdivision: str | None = None

    def __str__(self) -> str:
        place = f"{self.country_code}/{self.subdivision}" if self.subdivision else self.country_code
        return f"{self.name} ({self.latitude:.2f}, {self.longitude:.2f}, {place})"
