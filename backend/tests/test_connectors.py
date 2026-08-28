"""Connector smoke tests.

The valuable thing to prove here is the *round trip*: authorisation redirects to
the real platform, the callback's signature is checked, the token is stored
encrypted, a sync writes a dataset, and that dataset then forecasts through the
ordinary pipeline with no special casing. Shopify's HTTP endpoints are mocked
because a test suite cannot hold live merchant credentials -- but every layer of
our own code in that path is the real one, including the HMAC check.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import pytest

from app.services.connectors import crypto, service
from app.services.connectors.base import ConnectorError, normalise_frame
from app.services.connectors.registry import PROVIDERS
from app.services.connectors.shopify import ShopifyConnector, normalise_shop_domain

API_KEY = "test-api-key"
API_SECRET = "test-api-secret"
SHOP = "retailiq-demo.myshopify.com"


# ── the honesty rules the gallery is built on ────────────────────────────────
def test_every_provider_states_a_real_export_route():
    """No logo may exist without a way for the user to actually get their data."""
    for spec in PROVIDERS:
        assert spec.csv_route, f"{spec.key} has no CSV route"
        assert spec.summary, f"{spec.key} has no summary"
        assert spec.integration in {"live", "csv"}


def test_only_providers_with_real_oauth_claim_a_live_integration():
    live = {spec.key for spec in PROVIDERS if spec.integration == "live"}
    assert live == set(service.CONNECTORS), (
        "A provider is marked 'live' in the gallery without an implementation behind it."
    )


def test_live_providers_declare_the_credentials_they_need():
    for spec in PROVIDERS:
        if spec.integration == "live":
            assert spec.credentials, f"{spec.key} claims OAuth but names no credentials"


# ── normalisation ────────────────────────────────────────────────────────────
def test_shop_domain_accepts_the_forms_people_actually_paste():
    assert normalise_shop_domain("my-store") == "my-store.myshopify.com"
    assert normalise_shop_domain("my-store.myshopify.com") == "my-store.myshopify.com"
    assert normalise_shop_domain("https://my-store.myshopify.com/admin") == (
        "my-store.myshopify.com"
    )


def test_shop_domain_rejects_an_open_redirect():
    with pytest.raises(ConnectorError):
        normalise_shop_domain("evil.example.com/../")


def test_returns_are_excluded_rather_than_netted_off():
    frame = normalise_frame([
        {"date": "2024-01-01T00:00:00Z", "product": "Mug", "units": 5},
        {"date": "2024-01-01T00:00:00Z", "product": "Mug", "units": -2},
        {"date": "not-a-date", "product": "Mug", "units": 3},
        {"date": "2024-01-02T00:00:00Z", "product": "", "units": 4},
    ])
    assert len(frame) == 1
    assert frame.iloc[0]["units"] == 5


# ── tokens ───────────────────────────────────────────────────────────────────
def test_tokens_round_trip_through_encryption():
    secret = "shpat_super_secret_value"
    stored = crypto.encrypt(secret)
    assert stored is not None and secret not in stored
    assert crypto.decrypt(stored) == secret


def test_an_unreadable_token_is_a_reconnect_prompt_not_a_crash():
    assert crypto.decrypt("not-a-valid-fernet-token") is None


# ── OAuth ────────────────────────────────────────────────────────────────────
@pytest.fixture
def shopify_app(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RETAILIQ_SHOPIFY_API_KEY", API_KEY)
    monkeypatch.setenv("RETAILIQ_SHOPIFY_API_SECRET", API_SECRET)
    monkeypatch.setenv("RETAILIQ_SECRET_KEY", "test-secret-key-for-connector-tokens")
    crypto._box.cache_clear()
    yield
    get_settings.cache_clear()
    crypto._box.cache_clear()


def sign(params: dict[str, str]) -> str:
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "hmac")
    return hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()


def test_authorize_url_points_at_the_merchants_own_shop(shopify_app):
    url = ShopifyConnector().authorize_url(
        "state-123", "http://localhost:8000/cb", shop="retailiq-demo"
    )
    assert url.startswith(f"https://{SHOP}/admin/oauth/authorize?")
    assert f"client_id={API_KEY}" in url
    assert "state=state-123" in url


def test_callback_signature_is_verified(shopify_app):
    connector = ShopifyConnector()
    params = {"code": "abc", "shop": SHOP, "state": "s", "timestamp": "1700000000"}
    params["hmac"] = sign(params)
    assert connector.verify_callback(params) is True

    tampered = {**params, "shop": "attacker.myshopify.com"}
    assert connector.verify_callback(tampered) is False


# ── the full round trip ──────────────────────────────────────────────────────
def _shopify_orders_payload() -> dict:
    """Two months of daily orders, shaped exactly like the Admin API's response."""
    start = datetime.now(UTC) - timedelta(days=45)
    nodes = []
    for day in range(45):
        created = (start + timedelta(days=day)).isoformat().replace("+00:00", "Z")
        nodes.append({
            "id": f"gid://shopify/Order/{day}",
            "name": f"#{1000 + day}",
            # Imported historical orders carry the real sale date on processedAt;
            # createdAt is the day they were pushed into Shopify. One order below
            # deliberately omits processedAt to exercise the fallback.
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "processedAt": created if day else None,
            "displayFinancialStatus": "PAID",
            "currencyCode": "GBP",
            "shippingAddress": {"country": "United Kingdom"},
            "billingAddress": None,
            "lineItems": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [{
                    "title": "Regency Cakestand",
                    "sku": "CAKE-01",
                    "quantity": 3 + (day % 4),
                    "product": {"productType": "Homeware"},
                    "originalUnitPriceSet": {"shopMoney": {"amount": "12.75"}},
                }],
            },
        })
    return {"data": {"orders": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                "nodes": nodes}}}


def _mock_shopify(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/oauth/access_token"):
        return httpx.Response(200, json={
            "access_token": "shpat_test_token", "scope": "read_orders,read_products",
        })
    if request.url.path.endswith("/graphql.json"):
        body = json.loads(request.content)
        if "shop {" in body["query"]:
            return httpx.Response(200, json={"data": {"shop": {
                "name": "RetailIQ Demo Store", "myshopifyDomain": SHOP,
                "currencyCode": "GBP", "ianaTimezone": "Europe/London",
            }}})
        return httpx.Response(200, json=_shopify_orders_payload())
    return httpx.Response(404)


@pytest.fixture
def mocked_shopify_http(monkeypatch):
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(_mock_shopify)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.services.connectors.shopify.httpx.AsyncClient", factory)


@pytest.mark.asyncio
async def test_connect_sync_and_forecast_round_trip(shopify_app, mocked_shopify_http):
    """Authorise, exchange, sync, then forecast the synced data as an ordinary dataset."""
    from app.db.session import session_scope
    from app.services import datasets

    with session_scope() as session:
        url = service.start_authorization(session, "shopify", shop="retailiq-demo")
        assert SHOP in url
        state = url.split("state=")[1].split("&")[0]

        params = {"code": "auth-code", "shop": SHOP, "state": state,
                  "timestamp": "1700000000"}
        params["hmac"] = sign(params)

        account = await service.complete_authorization(session, "shopify", params)
        assert account.label == "RetailIQ Demo Store"
        # The plaintext token must not be sitting in the column.
        assert "shpat_test_token" not in (account.access_token_encrypted or "")
        assert crypto.decrypt(account.access_token_encrypted) == "shpat_test_token"

        # The state token is single-use.
        with pytest.raises(ConnectorError):
            await service.complete_authorization(session, "shopify", params)

        result = await service.sync_account(session, account.id, days=60)
        account_id = account.id

    assert result["orders"] == 45
    assert result["rows"] == 45
    assert result["products"] == 1
    # The history must span the real sale dates, not the import date.
    assert result["span_days"] >= 44
    assert result["dataset"] == f"connector:{account_id}"

    # And now the payoff: it is just a dataset.
    dataset = datasets.resolve(f"connector:{account_id}")
    assert dataset.products() == ["Regency Cakestand"]
    summaries = datasets.list_connected()
    assert any(s.source == "connector" for s in summaries)

    from app.services.forecast_service import generate_forecast

    response = generate_forecast(
        dataset, product_name="Regency Cakestand", horizon=7,
        model_name="seasonal-naive", run_backtest_flag=False,
        use_covariates=False, include_brief=False,
    )
    assert len(response.forecast) == 7

    with session_scope() as session:
        service.disconnect(session, account_id)
    assert not service.dataset_path(account_id).exists()


@pytest.mark.asyncio
async def test_a_short_connector_history_is_refused_not_padded(
    shopify_app, mocked_shopify_http
):
    """The data-quality gate applies to live platform data exactly as it does to a CSV."""
    from app.core.errors import InsufficientDataError
    from app.db.session import session_scope
    from app.services import datasets
    from app.services.forecast_service import generate_forecast

    with session_scope() as session:
        url = service.start_authorization(session, "shopify", shop="retailiq-demo")
        state = url.split("state=")[1].split("&")[0]
        params = {"code": "c", "shop": SHOP, "state": state, "timestamp": "1"}
        params["hmac"] = sign(params)
        account = await service.complete_authorization(session, "shopify", params)
        await service.sync_account(session, account.id, days=60)
        account_id = account.id

    dataset = datasets.resolve(f"connector:{account_id}")
    # 45 days of history is under the 120-day recommendation but over the 30-day
    # floor, so trim it to prove the floor is what refuses.
    dataset.frame = dataset.frame.head(20)
    with pytest.raises(InsufficientDataError):
        generate_forecast(
            dataset, product_name="Regency Cakestand", horizon=7,
            model_name="seasonal-naive", run_backtest_flag=False,
            use_covariates=False, include_brief=False,
        )

    with session_scope() as session:
        service.disconnect(session, account_id)


# ── the demo seeder ──────────────────────────────────────────────────────────
def test_seeding_shifts_the_series_without_distorting_it():
    """The UCI data is from 2010-2011; a 2026 sync window cannot reach it.

    Shifting is legitimate for a demo store, but only if it is a pure translation:
    every interval, quantity and price must survive untouched, so the forecast is
    still learning the real shape of the series.
    """
    import sys
    from datetime import date, timedelta
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.seed_shopify import shift_to_recent

    original = pd.DataFrame({
        "Date": pd.to_datetime(["2010-11-04", "2010-11-05", "2010-11-09", "2011-12-09"]),
        "Product Name": ["Mug"] * 4,
        "units": [5, 9, 2, 7],
        "price": [1.25] * 4,
    })
    shifted, offset = shift_to_recent(original)

    # Ends yesterday, so it sits inside an ordinary sync window.
    assert shifted["Date"].max().date() == date.today() - timedelta(days=1)
    # A single constant offset -- not a rescale, not a resample.
    assert offset > 0
    assert (shifted["Date"] - original["Date"]).nunique() == 1
    # Gaps between trading days are preserved exactly.
    assert list(shifted["Date"].diff().dropna()) == list(original["Date"].diff().dropna())
    # Nothing about the demand itself changed.
    assert list(shifted["units"]) == list(original["units"])
    assert list(shifted["price"]) == list(original["price"])
