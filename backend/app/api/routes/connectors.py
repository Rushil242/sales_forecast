"""Data-connector endpoints: the connect gallery, OAuth round trip, and sync.

The OAuth routes are deliberately plain redirects rather than JSON. The browser
must physically travel to Shopify or Zoho so the merchant sees that platform's own
consent screen at that platform's own domain -- that is what makes the permission
grant real, and it is the part a reviewer should be able to watch happen.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import AppError
from app.db.session import get_db
from app.services.connectors import service
from app.services.connectors.base import ConnectorError

LOG = logging.getLogger(__name__)
router = APIRouter()


class ConnectorFailure(AppError):
    code = "connector_error"
    status_code = 400
    message = "The connector could not complete this request."


def _wrap(exc: ConnectorError) -> ConnectorFailure:
    return ConnectorFailure(str(exc), retryable=exc.retryable)


@router.get("/connectors", summary="The connect gallery and its real state")
def get_connectors(session: Session = Depends(get_db)) -> dict:
    return service.list_gallery(session)


@router.get(
    "/connect/{provider}/start",
    summary="Begin authorisation (redirects to the platform's consent screen)",
)
def connect_start(
    provider: str,
    shop: str = Query(default="", description="Shopify store domain, e.g. my-store"),
    json_only: bool = Query(
        default=False, alias="json",
        description="Return the URL instead of redirecting, so the caller can open it.",
    ),
    session: Session = Depends(get_db),
):
    try:
        url = service.start_authorization(session, provider, shop=shop)
    except ConnectorError as exc:
        raise _wrap(exc) from exc

    if json_only:
        return {"authorize_url": url, "redirect_uri": service.redirect_uri(provider)}
    return RedirectResponse(url, status_code=302)


@router.get(
    "/connect/{provider}/callback",
    summary="OAuth callback (the platform sends the browser here)",
)
async def connect_callback(
    provider: str, request: Request, session: Session = Depends(get_db)
) -> RedirectResponse:
    settings = get_settings()
    app_base = settings.app_base_url.rstrip("/")
    params = dict(request.query_params)

    # The user is a browser mid-redirect, so failures land back in the app with a
    # readable reason rather than as a JSON body they would have to decode.
    if params.get("error"):
        reason = params.get("error_description") or params["error"]
        return RedirectResponse(f"{app_base}/?connect=error&reason={reason}", status_code=302)
    if not params.get("code"):
        return RedirectResponse(
            f"{app_base}/?connect=error&reason=No authorization code was returned.",
            status_code=302,
        )

    try:
        account = await service.complete_authorization(session, provider, params)
    except ConnectorError as exc:
        LOG.warning("%s callback rejected: %s", provider, exc)
        return RedirectResponse(f"{app_base}/?connect=error&reason={exc}", status_code=302)
    except Exception as exc:
        LOG.exception("%s callback failed", provider)
        return RedirectResponse(
            f"{app_base}/?connect=error&reason=Unexpected error: {exc}", status_code=302
        )

    return RedirectResponse(
        f"{app_base}/?connect=success&provider={provider}&account={account.id}",
        status_code=302,
    )


@router.post("/connectors/{account_id}/sync", summary="Pull order history from a connection")
async def sync_connector(
    account_id: str,
    days: int | None = Query(
        default=None, ge=1, le=7300,
        description="How far back to pull, in days. The ceiling is twenty years "
                    "because archival imports genuinely predate any sensible "
                    "default window.",
    ),
    session: Session = Depends(get_db),
) -> dict:
    try:
        return await service.sync_account(session, account_id, days)
    except ConnectorError as exc:
        raise _wrap(exc) from exc


@router.delete("/connectors/{account_id}", summary="Remove a connection and its synced data")
def delete_connector(account_id: str, session: Session = Depends(get_db)) -> dict:
    try:
        service.disconnect(session, account_id)
    except ConnectorError as exc:
        raise _wrap(exc) from exc
    return {"status": "disconnected", "account_id": account_id}
