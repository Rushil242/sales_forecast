"""Zoho Books / Inventory: real OAuth 2.0 with refresh, and invoice history.

Zoho is here because it is the accounting suite Indian small retailers actually
run, and because -- unlike Tally, Vyapar or myBillBook -- it exposes a public
OAuth app that any developer can register for free. That combination is rare
enough that it is worth saying out loud in a review.

Two things about Zoho shape this module:

**Regional data centres are not interchangeable.** A token minted by
``accounts.zoho.in`` is rejected by ``zohoapis.com``. The token response carries
the correct ``api_domain`` and we store that rather than guessing.

**Line items are only served per invoice.** The invoice *list* endpoint returns
totals but no items, so item-level demand needs one extra call per invoice. That
is a real cost, not a design choice we can optimise away, so the sync is bounded
by ``RETAILIQ_ZOHO_MAX_INVOICES`` and reports plainly when it hit that bound
instead of presenting a truncated history as if it were complete.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.connectors.base import (
    ConnectorError,
    ProviderSpec,
    SalesConnector,
    SyncResult,
    normalise_frame,
)
from app.services.connectors.registry import BY_KEY

LOG = logging.getLogger(__name__)

# Zoho runs independent data centres. Picking the wrong one produces an opaque
# "invalid oauth token", so the mapping is explicit.
ACCOUNTS_DOMAIN = {
    "in": "accounts.zoho.in",
    "com": "accounts.zoho.com",
    "eu": "accounts.zoho.eu",
    "au": "accounts.zoho.com.au",
    "jp": "accounts.zoho.jp",
    "ca": "accounts.zohocloud.ca",
}
API_DOMAIN = {
    "in": "https://www.zohoapis.in",
    "com": "https://www.zohoapis.com",
    "eu": "https://www.zohoapis.eu",
    "au": "https://www.zohoapis.com.au",
    "jp": "https://www.zohoapis.jp",
    "ca": "https://www.zohoapis.ca",
}

SCOPES = "ZohoBooks.invoices.READ,ZohoBooks.settings.READ"

# Concurrency for the per-invoice detail calls. Zoho's free plan meters requests
# per minute per organisation; six in flight stays comfortably inside it.
DETAIL_CONCURRENCY = 6


class ZohoConnector(SalesConnector):
    spec: ProviderSpec = BY_KEY["zoho"]

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def accounts_base(self) -> str:
        return f"https://{ACCOUNTS_DOMAIN[self.settings.zoho_region]}"

    def configured(self) -> bool:
        return self.settings.has_zoho

    def missing_credentials(self) -> list[str]:
        missing = []
        if not self.settings.zoho_client_id:
            missing.append("RETAILIQ_ZOHO_CLIENT_ID")
        if not self.settings.zoho_client_secret:
            missing.append("RETAILIQ_ZOHO_CLIENT_SECRET")
        return missing

    # ── step 1 ───────────────────────────────────────────────────────────────
    def authorize_url(self, state: str, redirect_uri: str, **params: str) -> str:
        if not self.configured():
            raise ConnectorError(
                "Zoho app credentials are not configured. Set "
                + " and ".join(self.missing_credentials())
                + " in your .env, then restart the API."
            )
        query = urlencode({
            "scope": SCOPES,
            "client_id": self.settings.zoho_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            # offline + consent is what makes Zoho issue a refresh token. Without
            # it the connection silently dies after one hour.
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"{self.accounts_base}/oauth/v2/auth?{query}"

    # ── step 2 ───────────────────────────────────────────────────────────────
    async def exchange_code(
        self, code: str, redirect_uri: str, **params: str
    ) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self.settings.connector_timeout) as client:
            response = await client.post(
                f"{self.accounts_base}/oauth/v2/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.settings.zoho_client_id,
                    "client_secret": self.settings.zoho_client_secret,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            payload = response.json() if response.content else {}

        if "error" in payload or not payload.get("access_token"):
            raise ConnectorError(
                f"Zoho rejected the authorization code ({payload.get('error', 'unknown error')}). "
                "Check that the redirect URI registered in the Zoho API console matches "
                f"{redirect_uri} exactly, and that the app's data centre is "
                f"'{self.settings.zoho_region}'."
            )

        token = payload["access_token"]
        api_domain = payload.get("api_domain") or API_DOMAIN[self.settings.zoho_region]
        expires_at = datetime.now(UTC) + timedelta(seconds=int(payload.get("expires_in", 3600)))

        organisation = await self._first_organisation(api_domain, token)
        return {
            "access_token": token,
            "refresh_token": payload.get("refresh_token"),
            "expires_at": expires_at,
            "scopes": payload.get("scope", SCOPES),
            "label": organisation.get("name") or "Zoho Books organisation",
            "external_id": organisation.get("organization_id"),
            "meta": {
                "api_domain": api_domain,
                "organization_id": organisation.get("organization_id"),
                "currency": organisation.get("currency_code"),
                "country": organisation.get("country"),
            },
        }

    async def refresh(self, refresh_token: str) -> dict[str, object]:
        """Zoho access tokens last an hour; the refresh token is long-lived."""
        async with httpx.AsyncClient(timeout=self.settings.connector_timeout) as client:
            response = await client.post(
                f"{self.accounts_base}/oauth/v2/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.settings.zoho_client_id,
                    "client_secret": self.settings.zoho_client_secret,
                    "refresh_token": refresh_token,
                },
            )
            payload = response.json() if response.content else {}

        if not payload.get("access_token"):
            raise ConnectorError(
                "Zoho would not refresh this connection. Reconnect the organisation."
            )
        return {
            "access_token": payload["access_token"],
            "expires_at": datetime.now(UTC)
            + timedelta(seconds=int(payload.get("expires_in", 3600))),
        }

    # ── API helpers ──────────────────────────────────────────────────────────
    async def _get(
        self, client: httpx.AsyncClient, api_domain: str, path: str,
        token: str, params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
        for attempt in range(4):
            response = await client.get(
                f"{api_domain}{path}", headers=headers, params=params or {}
            )
            if response.status_code == 429:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if response.status_code == 401:
                raise ConnectorError("Zoho rejected the token. Reconnect the organisation.")
            payload = response.json() if response.content else {}
            code = payload.get("code")
            if code not in (None, 0):
                raise ConnectorError(f"Zoho error {code}: {payload.get('message', '')}")
            return payload
        raise ConnectorError("Zoho kept rate-limiting the request. Try again shortly.",
                             retryable=True)

    async def _first_organisation(self, api_domain: str, token: str) -> dict[str, object]:
        async with httpx.AsyncClient(timeout=self.settings.connector_timeout) as client:
            payload = await self._get(client, api_domain, "/books/v3/organizations", token)
        organisations = payload.get("organizations") or []
        configured = self.settings.zoho_organization_id
        if configured:
            for organisation in organisations:
                if str(organisation.get("organization_id")) == str(configured):
                    return organisation
        if not organisations:
            raise ConnectorError(
                "This Zoho account has no Books organisation. Create one at books.zoho.in "
                "and reconnect."
            )
        return organisations[0]

    # ── step 3 ───────────────────────────────────────────────────────────────
    async def fetch_orders(
        self, account: dict[str, object], since: date, until: date
    ) -> SyncResult:
        token = str(account.get("access_token") or "")
        meta = account.get("meta") or {}
        api_domain = str(meta.get("api_domain") or API_DOMAIN[self.settings.zoho_region])
        organization_id = str(meta.get("organization_id") or "")
        if not token or not organization_id:
            raise ConnectorError("This Zoho connection is incomplete. Reconnect it.")

        warnings: list[str] = []
        limit = self.settings.zoho_max_invoices

        async with httpx.AsyncClient(timeout=self.settings.connector_timeout) as client:
            summaries = await self._list_invoices(
                client, api_domain, token, organization_id, since, until, limit
            )
            if len(summaries) >= limit:
                warnings.append(
                    f"Stopped after {limit:,} invoices, which is the configured ceiling. "
                    "Raise RETAILIQ_ZOHO_MAX_INVOICES or narrow the date range to pull "
                    "the rest -- the history below is real but incomplete."
                )

            rows, failures = await self._fetch_line_items(
                client, api_domain, token, organization_id, summaries
            )

        if failures:
            warnings.append(
                f"{failures} of {len(summaries)} invoices could not be read and were "
                "left out rather than estimated."
            )

        frame = normalise_frame(rows)
        return SyncResult(
            provider="zoho",
            account_label=str(account.get("label") or "Zoho Books"),
            frame=frame,
            orders=len(summaries),
            line_items=len(rows),
            first_date=frame["date"].min().strftime("%Y-%m-%d") if not frame.empty else None,
            last_date=frame["date"].max().strftime("%Y-%m-%d") if not frame.empty else None,
            warnings=warnings,
        )

    async def _list_invoices(
        self, client: httpx.AsyncClient, api_domain: str, token: str,
        organization_id: str, since: date, until: date, limit: int,
    ) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        page = 1
        while len(summaries) < limit:
            payload = await self._get(
                client, api_domain, "/books/v3/invoices", token,
                {
                    "organization_id": organization_id,
                    "date_start": since.isoformat(),
                    "date_end": until.isoformat(),
                    "per_page": 200,
                    "page": page,
                    "sort_column": "date",
                    "sort_order": "A",
                },
            )
            batch = payload.get("invoices") or []
            summaries.extend(batch)
            context = payload.get("page_context") or {}
            if not batch or not context.get("has_more_page"):
                break
            page += 1
        return summaries[:limit]

    async def _fetch_line_items(
        self, client: httpx.AsyncClient, api_domain: str, token: str,
        organization_id: str, summaries: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], int]:
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        rows: list[dict[str, object]] = []
        failures = 0

        async def one(summary: dict[str, object]) -> list[dict[str, object]] | None:
            invoice_id = summary.get("invoice_id")
            if not invoice_id:
                return None
            async with semaphore:
                try:
                    payload = await self._get(
                        client, api_domain, f"/books/v3/invoices/{invoice_id}", token,
                        {"organization_id": organization_id},
                    )
                except Exception as exc:
                    LOG.debug("Zoho invoice %s failed: %s", invoice_id, exc)
                    return None

            invoice = payload.get("invoice") or {}
            invoice_date = invoice.get("date") or summary.get("date")
            billing = invoice.get("billing_address") or {}
            place = invoice.get("place_of_supply") or billing.get("state")
            out: list[dict[str, object]] = []
            for item in invoice.get("line_items") or []:
                quantity = item.get("quantity") or 0
                try:
                    quantity = float(quantity)
                except (TypeError, ValueError):
                    continue
                if quantity <= 0:
                    continue
                rate = item.get("rate")
                try:
                    rate = float(rate) if rate is not None else None
                except (TypeError, ValueError):
                    rate = None
                out.append({
                    "date": invoice_date,
                    "product": item.get("name") or item.get("description") or "Unknown item",
                    "units": quantity,
                    "unit_price": rate,
                    "revenue": item.get("item_total"),
                    "region": place or None,
                    "transaction_id": invoice.get("invoice_number") or str(invoice_id),
                })
            return out

        results = await asyncio.gather(*(one(s) for s in summaries), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) or result is None:
                failures += 1
                continue
            rows.extend(result)
        return rows, failures
