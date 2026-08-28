"""Contracts shared by every sales-data connector.

A connector's job is narrow: authenticate against a platform the retailer already
uses, pull their order history, and hand back a frame in the same shape
``services/ingestion.py`` already accepts. Everything downstream -- series
building, the data-quality gate, forecasting, the backtest -- then works on
connector data exactly as it works on an uploaded CSV, with no special cases.

Two honesty rules govern this package, and they are the reason the gallery looks
the way it does:

**No mocked data behind any logo.** A provider is either genuinely implemented
(real OAuth, real API) or it is listed with a real, specific CSV export route out
of that platform. There is no third state where a logo produces invented orders.

**Missing credentials are stated, not hidden.** A provider we have built but that
has no API keys configured reports ``needs_credentials`` and names the exact
environment variables required, rather than failing at the moment the user clicks.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

LOG = logging.getLogger(__name__)

# The columns every connector must produce. These are the canonical names
# `services/ingestion.py` resolves to, so a connector frame needs no translation.
REQUIRED_COLUMNS = ("date", "product", "units")
OPTIONAL_COLUMNS = ("unit_price", "revenue", "region", "category", "transaction_id")


@dataclass(frozen=True)
class ProviderSpec:
    """Everything the connect gallery needs to describe one platform honestly."""

    key: str
    name: str
    category: str          # ecommerce | accounting | payments | marketplace | pos
    region: str            # global | india | uk
    integration: str       # live | csv
    auth: str              # oauth | csv
    summary: str
    pulls: tuple[str, ...] = ()
    # Exact steps to export a CSV from this platform. Present for every provider,
    # including the live ones -- OAuth can fail, and the fallback is real.
    csv_route: str = ""
    docs_url: str = ""
    # Environment variables that must be set before OAuth can be attempted.
    credentials: tuple[str, ...] = ()
    mark: str = ""         # two-letter mark shown in the gallery tile
    accent: str = "#475569"


@dataclass
class SyncResult:
    """Outcome of pulling order history from a connected account."""

    provider: str
    account_label: str
    frame: pd.DataFrame
    orders: int = 0
    line_items: int = 0
    first_date: str | None = None
    last_date: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return len(self.frame)


class ConnectorError(Exception):
    """A connector could not complete its work, with a message fit for a user."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class SalesConnector(ABC):
    """A platform we can pull real order history out of."""

    spec: ProviderSpec

    @abstractmethod
    def authorize_url(self, state: str, redirect_uri: str, **params: str) -> str:
        """The platform's own consent screen. The user goes there, not to us."""

    @abstractmethod
    async def exchange_code(
        self, code: str, redirect_uri: str, **params: str
    ) -> dict[str, object]:
        """Trade the callback's authorization code for tokens plus account metadata."""

    @abstractmethod
    async def fetch_orders(
        self, account: dict[str, object], since: date, until: date
    ) -> SyncResult:
        """Pull order history for the window and return it in canonical shape."""

    def configured(self) -> bool:
        """True when the credentials this connector needs are actually present."""
        return True

    def missing_credentials(self) -> list[str]:
        return []


def normalise_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Coerce connector rows into the canonical frame, dropping what cannot be used.

    Returns are excluded rather than netted off, matching the CSV path: a refund is
    a real event but it is not demand, and silently subtracting it would misstate
    what the shop actually sold on that day.
    """
    if not rows:
        return pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    frame = pd.DataFrame(rows)
    for column in REQUIRED_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    frame = frame.dropna(subset=["date"])
    # Platform timestamps are UTC-aware; the series layer works in naive local days.
    frame["date"] = frame["date"].dt.tz_localize(None).dt.normalize()

    frame["product"] = frame["product"].astype(str).str.strip()
    frame["units"] = pd.to_numeric(frame["units"], errors="coerce")
    frame = frame.dropna(subset=["units"])
    frame = frame[frame["units"] > 0]
    frame = frame[frame["product"].str.len() > 0]

    keep = [c for c in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if c in frame.columns]
    return frame[keep].sort_values("date").reset_index(drop=True)
