"""Shopify: real OAuth 2.0 and the GraphQL Admin API.

Flow, end to end
----------------
1. ``authorize_url`` builds a link to *the merchant's own* shop domain. We never
   see their Shopify password -- they log in at Shopify and approve the scopes on
   Shopify's screen.
2. Shopify redirects back with ``code``, ``hmac``, ``shop`` and our ``state``.
   ``verify_callback`` checks the HMAC against the app secret before anything else
   happens, which is what stops a forged callback from planting a token.
3. ``exchange_code`` trades the code for a permanent access token.
4. ``fetch_orders`` pages through the Admin GraphQL API and returns line items in
   the canonical frame shape.

The 60-day wall
---------------
Shopify's ``read_orders`` scope only exposes the **last 60 days** of orders. Older
history needs ``read_all_orders``, which Shopify grants on request and enables
freely on development stores. A forecast trained on 60 days of history is a much
weaker forecast, so rather than quietly returning a short series this connector
detects the clipped window and says which scope is missing.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import date
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

ORDERS_QUERY = """
query RetailIQOrders($cursor: String, $filter: String!) {
  orders(first: 50, after: $cursor, query: $filter, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      processedAt
      displayFinancialStatus
      currencyCode
      shippingAddress { city country }
      billingAddress { city country }
      lineItems(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          title
          sku
          quantity
          product { productType }
          originalUnitPriceSet { shopMoney { amount } }
        }
      }
    }
  }
}
"""

SHOP_QUERY = """
query { shop { name myshopifyDomain email currencyCode ianaTimezone } }
"""


def normalise_shop_domain(shop: str) -> str:
    """Accept 'my-store', 'my-store.myshopify.com' or a full URL; return the domain."""
    value = (shop or "").strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    value = value.split("/")[0].strip()
    if not value:
        raise ConnectorError("A Shopify store domain is required, e.g. my-store.myshopify.com")
    if not value.endswith(".myshopify.com"):
        value = f"{value}.myshopify.com"
    # Guard against an open redirect: only ever send the browser to Shopify.
    if not value.replace(".myshopify.com", "").replace("-", "").isalnum():
        raise ConnectorError(f"'{shop}' is not a valid Shopify store domain.")
    return value


class ShopifyConnector(SalesConnector):
    spec: ProviderSpec = BY_KEY["shopify"]

    def __init__(self) -> None:
        self.settings = get_settings()

    # ── credentials ──────────────────────────────────────────────────────────
    def configured(self) -> bool:
        return self.settings.has_shopify

    def missing_credentials(self) -> list[str]:
        missing = []
        if not self.settings.shopify_api_key:
            missing.append("RETAILIQ_SHOPIFY_API_KEY")
        if not self.settings.shopify_api_secret:
            missing.append("RETAILIQ_SHOPIFY_API_SECRET")
        return missing

    # ── step 1: send the merchant to Shopify ─────────────────────────────────
    def authorize_url(self, state: str, redirect_uri: str, **params: str) -> str:
        if not self.configured():
            raise ConnectorError(
                "Shopify app credentials are not configured. Set "
                + " and ".join(self.missing_credentials())
                + " in your .env, then restart the API."
            )
        shop = normalise_shop_domain(params.get("shop", ""))
        query = urlencode({
            "client_id": self.settings.shopify_api_key,
            "scope": self.settings.shopify_scopes,
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"https://{shop}/admin/oauth/authorize?{query}"

    # ── step 2: prove the callback really came from Shopify ──────────────────
    def verify_callback(self, params: dict[str, str]) -> bool:
        """Constant-time HMAC check over the callback query string."""
        received = params.get("hmac", "")
        if not received or not self.settings.shopify_api_secret:
            return False
        # Every parameter except `hmac` itself, sorted, joined as a query string.
        message = "&".join(
            f"{key}={value}" for key, value in sorted(params.items()) if key != "hmac"
        )
        expected = hmac.new(
            self.settings.shopify_api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received)

    # ── step 3: code -> access token ─────────────────────────────────────────
    async def exchange_code(
        self, code: str, redirect_uri: str, **params: str
    ) -> dict[str, object]:
        shop = normalise_shop_domain(params.get("shop", ""))
        async with httpx.AsyncClient(timeout=self.settings.connector_timeout) as client:
            response = await client.post(
                f"https://{shop}/admin/oauth/access_token",
                json={
                    "client_id": self.settings.shopify_api_key,
                    "client_secret": self.settings.shopify_api_secret,
                    "code": code,
                },
            )
            if response.status_code != 200:
                raise ConnectorError(
                    f"Shopify rejected the authorization code ({response.status_code}). "
                    "This usually means the redirect URI in your app settings does not "
                    "exactly match the one this server is using."
                )
            payload = response.json()

        token = payload.get("access_token")
        if not token:
            raise ConnectorError("Shopify returned no access token.")

        shop_info = await self._shop_info(shop, token)
        return {
            "access_token": token,
            "refresh_token": None,
            "expires_at": None,
            "scopes": payload.get("scope", ""),
            "label": shop_info.get("name") or shop,
            "external_id": shop,
            "meta": {"shop": shop, **shop_info},
        }

    async def _shop_info(self, shop: str, token: str) -> dict[str, object]:
        try:
            data = await self._graphql(shop, token, SHOP_QUERY, {})
            return data.get("shop", {}) or {}
        except Exception as exc:
            LOG.warning("Could not read Shopify shop metadata: %s", exc)
            return {}

    # ── step 4: pull the orders ──────────────────────────────────────────────
    async def _graphql(
        self, shop: str, token: str, query: str, variables: dict[str, object]
    ) -> dict[str, object]:
        url = f"https://{shop}/admin/api/{self.settings.shopify_api_version}/graphql.json"
        headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=self.settings.connector_timeout) as client:
            for attempt in range(4):
                response = await client.post(
                    url, headers=headers, json={"query": query, "variables": variables}
                )
                if response.status_code == 401:
                    raise ConnectorError(
                        "Shopify rejected the stored token. Reconnect the store."
                    )
                if response.status_code == 429:
                    # Shopify's GraphQL bucket refills at a steady rate; backing
                    # off is the documented remedy, not an error.
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                response.raise_for_status()
                payload = response.json()

                errors = payload.get("errors")
                if errors:
                    codes = {
                        (e.get("extensions") or {}).get("code")
                        for e in errors if isinstance(e, dict)
                    }
                    if "THROTTLED" in codes:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    message = "; ".join(
                        str(e.get("message", e)) for e in errors if isinstance(e, dict)
                    )
                    if "not approved to access the Order object" in message:
                        # Orders carry customer PII. Scopes alone are not enough:
                        # Shopify requires a separate Protected Customer Data
                        # approval, and telling someone to "reconnect" here sends
                        # them round a loop that cannot fix it.
                        raise ConnectorError(
                            "Shopify is withholding order data because this app has "
                            "not been granted Protected Customer Data access. Open the "
                            "app in your Shopify Dev Dashboard, request access to "
                            "customer data (it is granted immediately on development "
                            "stores), then sync again. Scopes and tokens are fine -- "
                            "this is a separate approval."
                        )
                    if "access denied" in message.lower() or "ACCESS_DENIED" in codes:
                        raise ConnectorError(
                            f"Shopify denied the request: {message}. The app's granted "
                            "scopes may not cover orders -- reconnect the store."
                        )
                    raise ConnectorError(f"Shopify GraphQL error: {message}")

                return payload.get("data") or {}

        raise ConnectorError("Shopify kept throttling the request. Try again shortly.",
                             retryable=True)

    async def fetch_orders(
        self, account: dict[str, object], since: date, until: date
    ) -> SyncResult:
        token = str(account.get("access_token") or "")
        meta = account.get("meta") or {}
        shop = str(meta.get("shop") or account.get("external_id") or "")
        if not token or not shop:
            raise ConnectorError("This Shopify connection is missing its token. Reconnect it.")

        scopes = str(account.get("scopes") or "")
        # processed_at is when the sale actually happened, which is what Shopify's
        # own analytics reports on and what an imported historical order carries.
        # created_at would date every backfilled order to the day it was imported.
        filter_query = (
            f"processed_at:>={since.isoformat()} AND processed_at:<={until.isoformat()}"
        )

        rows: list[dict[str, object]] = []
        warnings: list[str] = []
        orders = 0
        truncated_line_items = 0
        cursor: str | None = None
        pages = 0

        while True:
            data = await self._graphql(
                shop, token, ORDERS_QUERY, {"cursor": cursor, "filter": filter_query}
            )
            block = data.get("orders") or {}
            nodes = block.get("nodes") or []

            for order in nodes:
                orders += 1
                created = order.get("processedAt") or order.get("createdAt")
                ship = order.get("shippingAddress") or {}
                bill = order.get("billingAddress") or {}
                # City is the useful grain for a retail chain -- "India" tells a buyer
                # nothing, "Delhi" tells them where the hoodies went. Fall back to
                # country when a store does not capture city.
                country = (ship.get("city") or bill.get("city")
                           or ship.get("country") or bill.get("country"))
                line_block = order.get("lineItems") or {}
                if (line_block.get("pageInfo") or {}).get("hasNextPage"):
                    truncated_line_items += 1

                for item in line_block.get("nodes") or []:
                    quantity = item.get("quantity") or 0
                    if quantity <= 0:
                        continue
                    price = (
                        ((item.get("originalUnitPriceSet") or {}).get("shopMoney") or {})
                        .get("amount")
                    )
                    unit_price = float(price) if price is not None else None
                    rows.append({
                        "date": created,
                        "product": item.get("title") or item.get("sku") or "Unknown item",
                        "units": quantity,
                        "unit_price": unit_price,
                        "revenue": (unit_price * quantity) if unit_price is not None else None,
                        "region": country,
                        "category": (item.get("product") or {}).get("productType") or None,
                        "transaction_id": order.get("name") or order.get("id"),
                    })

            page_info = block.get("pageInfo") or {}
            pages += 1
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            # A dev store cannot realistically exceed this; the guard exists so a
            # pagination bug cannot turn into an unbounded loop against a real shop.
            if pages >= 400:
                warnings.append(
                    "Stopped after 20,000 orders. Narrow the sync window to pull the rest."
                )
                break

        frame = normalise_frame(rows)

        if truncated_line_items:
            warnings.append(
                f"{truncated_line_items} order(s) contained more than 100 line items; "
                "only the first 100 of each were read."
            )

        # The 60-day wall, detected rather than assumed.
        #
        # The obvious test -- "the earliest order is later than we asked for" -- is
        # wrong, and confidently so: a store that simply has no older orders trips
        # it every time. That produced a warning telling the user their history had
        # been clipped by a scope when in fact they had received all of it, which is
        # exactly the kind of assured-but-false statement this project exists to
        # avoid. What actually identifies the wall is the *width* of what came back
        # sitting right at the 60-day cap while a much longer window was requested.
        if not frame.empty and "read_all_orders" not in scopes:
            earliest = frame["date"].min().date()
            latest = frame["date"].max().date()
            returned_days = (latest - earliest).days + 1
            requested_days = (until - since).days
            looks_clipped = requested_days > 90 and returned_days <= 65
            if looks_clipped:
                warnings.append(
                    f"Shopify returned only {returned_days} days of orders "
                    f"({earliest.isoformat()} onward) though {requested_days} were "
                    "requested. That is the read_orders 60-day cap: ask Shopify to "
                    "enable read_all_orders and reconnect to pull full history."
                )

        return SyncResult(
            provider="shopify",
            account_label=str(account.get("label") or shop),
            frame=frame,
            orders=orders,
            line_items=len(rows),
            first_date=frame["date"].min().strftime("%Y-%m-%d") if not frame.empty else None,
            last_date=frame["date"].max().strftime("%Y-%m-%d") if not frame.empty else None,
            warnings=warnings,
        )
