"""Connector orchestration: authorise, store, sync, and hand over to forecasting.

The point of this layer is that a synced connector becomes an ordinary dataset.
Once ``sync`` has written its CSV, the forecast page treats ``connector:<id>``
exactly like the bundled UCI file or an upload -- same ingestion, same
data-quality gate, same refusal to forecast a series that is too short. Live
Shopify data gets no special dispensation, which is the whole point of routing it
through the same door.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ConnectorAccount, OAuthState
from app.services.connectors import crypto
from app.services.connectors.base import ConnectorError, SalesConnector, SyncResult
from app.services.connectors.registry import PROVIDERS
from app.services.connectors.registry import get as get_spec
from app.services.connectors.shopify import ShopifyConnector
from app.services.connectors.zoho import ZohoConnector

LOG = logging.getLogger(__name__)

CONNECTORS: dict[str, type[SalesConnector]] = {
    "shopify": ShopifyConnector,
    "zoho": ZohoConnector,
}

STATE_TTL_SECONDS = 900


def connector_for(provider: str) -> SalesConnector:
    factory = CONNECTORS.get(provider)
    if factory is None:
        spec = get_spec(provider)
        if spec is not None:
            raise ConnectorError(
                f"{spec.name} has no direct integration. {spec.csv_route}"
            )
        raise ConnectorError(f"Unknown provider '{provider}'.")
    return factory()


def sync_dir() -> Path:
    path = get_settings().data_dir / "connectors"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dataset_path(account_id: str) -> Path:
    return sync_dir() / f"{account_id}.csv"


def redirect_uri(provider: str) -> str:
    """The callback the platform must be configured to return to."""
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/api/v1/connect/{provider}/callback"


# ── gallery ──────────────────────────────────────────────────────────────────
def _account_payload(account: ConnectorAccount) -> dict[str, object]:
    return {
        "id": account.id,
        "provider": account.provider,
        "label": account.label,
        "status": account.status,
        "connected_at": account.created_at.isoformat(),
        "scopes": account.scopes,
        "dataset": f"connector:{account.id}" if account.last_sync_rows else None,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "last_sync_rows": account.last_sync_rows,
        "last_sync_products": account.last_sync_products,
        "last_sync_first_date": account.last_sync_first_date,
        "last_sync_last_date": account.last_sync_last_date,
        "last_sync_error": account.last_sync_error,
    }


def list_gallery(session: Session) -> dict[str, object]:
    """Every provider with its real state, plus the accounts already connected."""
    accounts = session.execute(
        select(ConnectorAccount).order_by(ConnectorAccount.created_at.desc())
    ).scalars().all()
    by_provider: dict[str, list[dict[str, object]]] = {}
    for account in accounts:
        by_provider.setdefault(account.provider, []).append(_account_payload(account))

    entries = []
    for spec in PROVIDERS:
        connected = by_provider.get(spec.key, [])
        missing: list[str] = []
        if spec.integration == "live":
            connector = connector_for(spec.key)
            missing = connector.missing_credentials()
            if connected:
                state = "connected"
            elif missing:
                state = "needs_credentials"
            else:
                state = "ready"
        else:
            state = "csv"

        entries.append({
            "key": spec.key,
            "name": spec.name,
            "category": spec.category,
            "region": spec.region,
            "integration": spec.integration,
            "auth": spec.auth,
            "summary": spec.summary,
            "pulls": list(spec.pulls),
            "csv_route": spec.csv_route,
            "docs_url": spec.docs_url,
            "mark": spec.mark,
            "accent": spec.accent,
            "state": state,
            "missing_credentials": missing,
            "accounts": connected,
            "redirect_uri": redirect_uri(spec.key) if spec.integration == "live" else None,
        })

    return {
        "providers": entries,
        "token_storage": "encrypted" if not crypto.key_is_ephemeral() else "ephemeral",
        "token_storage_note": (
            crypto.EPHEMERAL_WARNING if crypto.key_is_ephemeral()
            else "Access tokens are encrypted at rest with RETAILIQ_SECRET_KEY."
        ),
    }


# ── authorisation ────────────────────────────────────────────────────────────
def start_authorization(session: Session, provider: str, **params: str) -> str:
    connector = connector_for(provider)
    state = secrets.token_urlsafe(32)

    session.add(OAuthState(
        state=state,
        provider=provider,
        expires_at=datetime.now(UTC) + timedelta(seconds=STATE_TTL_SECONDS),
        payload={k: v for k, v in params.items() if v},
    ))
    session.commit()

    url = connector.authorize_url(state, redirect_uri(provider), **params)
    LOG.info("Starting %s authorisation, redirecting to the platform", provider)
    return url


def _consume_state(session: Session, provider: str, state: str) -> dict[str, object]:
    row = session.get(OAuthState, state)
    if row is None or row.provider != provider or row.used:
        raise ConnectorError(
            "This authorisation link is not valid any more. Start the connection again."
        )
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        raise ConnectorError("The authorisation timed out. Start the connection again.")
    row.used = True
    session.commit()
    return dict(row.payload or {})


async def complete_authorization(
    session: Session, provider: str, params: dict[str, str]
) -> ConnectorAccount:
    connector = connector_for(provider)

    state = params.get("state", "")
    stored = _consume_state(session, provider, state)

    # Shopify signs its callback; verifying that signature is what makes the
    # callback trustworthy at all, so it happens before the code is used.
    verify = getattr(connector, "verify_callback", None)
    if verify is not None and not verify(params):
        raise ConnectorError(
            "The callback signature did not match. The request was not accepted."
        )

    extra = {"shop": params.get("shop") or str(stored.get("shop", ""))}
    result = await connector.exchange_code(params["code"], redirect_uri(provider), **extra)

    external_id = result.get("external_id")
    existing = None
    if external_id:
        existing = session.execute(
            select(ConnectorAccount).where(
                ConnectorAccount.provider == provider,
                ConnectorAccount.external_id == str(external_id),
            )
        ).scalar_one_or_none()

    account = existing or ConnectorAccount(provider=provider)
    account.label = str(result.get("label") or provider)
    account.external_id = str(external_id) if external_id else None
    account.access_token_encrypted = crypto.encrypt(str(result["access_token"]))
    refresh_token = result.get("refresh_token")
    if refresh_token:
        account.refresh_token_encrypted = crypto.encrypt(str(refresh_token))
    account.token_expires_at = result.get("expires_at")  # type: ignore[assignment]
    account.scopes = str(result.get("scopes") or "")
    account.meta = result.get("meta") or {}
    account.status = "connected"
    account.last_sync_error = None

    session.add(account)
    session.commit()
    LOG.info("Connected %s account '%s'", provider, account.label)
    return account


def disconnect(session: Session, account_id: str) -> None:
    account = session.get(ConnectorAccount, account_id)
    if account is None:
        raise ConnectorError("That connection no longer exists.")
    path = dataset_path(account_id)
    if path.exists():
        path.unlink()
    session.delete(account)
    session.commit()
    LOG.info("Disconnected %s account %s", account.provider, account_id)


# ── sync ─────────────────────────────────────────────────────────────────────
async def _account_credentials(
    session: Session, account: ConnectorAccount, connector: SalesConnector
) -> dict[str, object]:
    token = crypto.decrypt(account.access_token_encrypted)
    if token is None:
        account.status = "needs_reconnect"
        session.commit()
        raise ConnectorError(
            "The stored token for this connection cannot be read, which happens when "
            "RETAILIQ_SECRET_KEY changes or was never set. Reconnect the account."
        )

    expires = account.token_expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        refresher = getattr(connector, "refresh", None)
        if refresher is not None and expires < datetime.now(UTC) + timedelta(minutes=2):
            refresh_token = crypto.decrypt(account.refresh_token_encrypted)
            if refresh_token is None:
                raise ConnectorError(
                    "This connection's access token has expired and no refresh token is "
                    "stored. Reconnect the account."
                )
            refreshed = await refresher(refresh_token)
            token = str(refreshed["access_token"])
            account.access_token_encrypted = crypto.encrypt(token)
            account.token_expires_at = refreshed.get("expires_at")  # type: ignore[assignment]
            session.commit()
            LOG.info("Refreshed %s token for '%s'", account.provider, account.label)

    return {
        "access_token": token,
        "label": account.label,
        "external_id": account.external_id,
        "scopes": account.scopes,
        "meta": account.meta or {},
    }


async def sync_account(
    session: Session, account_id: str, days: int | None = None
) -> dict[str, object]:
    account = session.get(ConnectorAccount, account_id)
    if account is None:
        raise ConnectorError("That connection no longer exists.")

    settings = get_settings()
    connector = connector_for(account.provider)
    window = days or settings.connector_sync_days
    until = date.today()
    since = until - timedelta(days=window)

    credentials = await _account_credentials(session, account, connector)

    try:
        result: SyncResult = await connector.fetch_orders(credentials, since, until)
    except ConnectorError as exc:
        account.last_sync_error = str(exc)
        account.status = "error"
        session.commit()
        raise

    warnings = list(result.warnings)
    products = int(result.frame["product"].nunique()) if not result.frame.empty else 0

    if result.frame.empty:
        account.last_sync_at = datetime.now(UTC)
        account.last_sync_rows = 0
        account.last_sync_products = 0
        account.last_sync_error = None
        account.status = "connected"
        session.commit()
        return {
            "account": _account_payload(account),
            "rows": 0,
            "orders": result.orders,
            "products": 0,
            "dataset": None,
            "warnings": warnings + [
                f"No orders were found between {since.isoformat()} and {until.isoformat()}. "
                "Nothing was imported -- an empty history cannot be forecast."
            ],
        }

    path = dataset_path(account_id)
    result.frame.to_csv(path, index=False)

    account.last_sync_at = datetime.now(UTC)
    account.last_sync_rows = result.rows
    account.last_sync_products = products
    account.last_sync_first_date = result.first_date
    account.last_sync_last_date = result.last_date
    account.last_sync_error = None
    account.status = "connected"
    session.commit()

    span = 0
    if result.first_date and result.last_date:
        span = (date.fromisoformat(result.last_date)
                - date.fromisoformat(result.first_date)).days + 1
    if span and span < settings.min_observations:
        warnings.append(
            f"This account holds only {span} days of history. The forecast endpoint "
            f"needs at least {settings.min_observations} days and will refuse below that, "
            "rather than padding the series."
        )

    LOG.info(
        "Synced %s '%s': %d line items across %d orders, %d products, %s to %s",
        account.provider, account.label, result.rows, result.orders, products,
        result.first_date, result.last_date,
    )

    return {
        "account": _account_payload(account),
        "rows": result.rows,
        "orders": result.orders,
        "products": products,
        "span_days": span,
        "dataset": f"connector:{account_id}",
        "warnings": warnings,
    }
