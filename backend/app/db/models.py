"""Persistence model.

Five tables, each earning its place:

``forecast_runs``    every forecast served, with its inputs, accuracy metrics and
                     timings -- this is what makes results reproducible and gives
                     the evaluation chapter real numbers to quote.
``social_snapshots`` a TTL cache of harvested social data, so re-running a
                     forecast for the same product does not re-scrape the
                     internet (and does not get us rate-limited).
``jobs``             async job records for long-running work, letting the API
                     return immediately instead of holding a request open.
``connector_accounts`` authorised connections to a retailer's own Shopify or Zoho,
                     with their OAuth tokens encrypted at rest.
``oauth_states``     one-shot CSRF tokens guarding an in-flight authorisation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    dataset_name: Mapped[str] = mapped_column(String(255))
    # Content hash of the input series, so identical inputs are recognisable
    # across uploads with different filenames.
    series_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    product_name: Mapped[str] = mapped_column(String(255), index=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)

    model_name: Mapped[str] = mapped_column(String(64))
    horizon_days: Mapped[int] = mapped_column(Integer)
    observations: Mapped[int] = mapped_column(Integer)
    history_start: Mapped[str] = mapped_column(String(10))
    history_end: Mapped[str] = mapped_column(String(10))

    fusion_applied: Mapped[bool] = mapped_column(default=False)
    fusion_elasticity: Mapped[float | None] = mapped_column(Float, nullable=True)
    fusion_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)

    total_predicted_units: Mapped[float] = mapped_column(Float)
    mean_predicted_units: Mapped[float] = mapped_column(Float)
    backtest_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    data_quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    duration_ms: Mapped[int] = mapped_column(Integer)

    __table_args__ = (Index("ix_forecast_runs_product_created", "product_name", "created_at"),)


class SocialSnapshot(Base):
    __tablename__ = "social_snapshots"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Normalised "<query>|<lookback_days>" so cache hits are exact.
    cache_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    query: Mapped[str] = mapped_column(String(255))
    lookback_days: Mapped[int] = mapped_column(Integer)

    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    document_count: Mapped[int] = mapped_column(Integer, default=0)
    connectors_used: Mapped[str] = mapped_column(String(255), default="")

    def is_fresh(self) -> bool:
        expires = self.expires_at
        if expires.tzinfo is None:  # SQLite hands back naive datetimes
            expires = expires.replace(tzinfo=UTC)
        return expires > _utcnow()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str] = mapped_column(String(128), default="queued")

    request: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConnectorAccount(Base):
    """One authorised connection to a retailer's own platform.

    Tokens are stored encrypted (see ``services/connectors/crypto.py``). The
    columns are deliberately named ``*_encrypted`` so that anyone reading a schema
    dump can see at a glance that the plaintext is not here.
    """

    __tablename__ = "connector_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    provider: Mapped[str] = mapped_column(String(32), index=True)
    # Human-readable identity of the connected account: a shop domain, an org name.
    label: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str] = mapped_column(String(512), default="")
    # Per-provider connection details: shop domain, API domain, organization id.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="connected", index=True)

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_rows: Mapped[int] = mapped_column(Integer, default=0)
    last_sync_products: Mapped[int] = mapped_column(Integer, default=0)
    last_sync_first_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_sync_last_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_connector_accounts_provider_status", "provider", "status"),)


class OAuthState(Base):
    """Short-lived CSRF token for an in-flight authorisation.

    The ``state`` parameter is what stops a third party from feeding us their own
    authorization code. It is generated before the redirect, checked on the way
    back, and consumed exactly once.
    """

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    used: Mapped[bool] = mapped_column(default=False)
