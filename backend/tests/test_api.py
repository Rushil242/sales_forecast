"""API contract tests, exercised through the real ASGI app."""

from __future__ import annotations

import io

import pytest

from app.services import datasets


@pytest.fixture(autouse=True)
def _isolate_dataset_cache():
    """Each test starts with a clean upload cache."""
    datasets._upload_cache.clear()
    datasets._bundled_cache.clear()
    yield
    datasets._upload_cache.clear()


def _upload(client, transactions, name="test.csv"):
    content = transactions.to_csv(index=False).encode()
    return client.post(
        "/api/v1/datasets/upload",
        files={"file": (name, io.BytesIO(content), "text/csv")},
    )


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_subsystems(client):
    payload = client.get("/ready").json()
    assert payload["database"] == "ok"
    assert "social" in payload

    forecasting = payload["forecasting"]
    assert forecasting["default_model"] == "chronos-2"
    # Only the covariate-capable model may claim covariate support.
    assert forecasting["chronos2"]["supports_covariates"] is True
    assert forecasting["chronos_bolt"]["supports_covariates"] is False

    assert "enrichment" in payload
    assert "narrative" in payload


def test_every_response_carries_a_request_id(client):
    response = client.get("/health")
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Process-Time-Ms"].isdigit()


def test_models_endpoint_lists_availability(client):
    models = client.get("/api/v1/models").json()
    names = {model["name"] for model in models}
    assert "seasonal-naive" in names
    assert all("available" in model for model in models)


def test_upload_returns_token_and_resolved_columns(client, transactions):
    payload = _upload(client, transactions).json()

    assert payload["token"].startswith("upload:")
    assert payload["resolved_columns"]["units"] == "Units Sold"
    assert payload["dataset"]["products"] == 2


def test_upload_rejects_bad_schema(client):
    content = b"foo,bar\n1,2\n"
    response = client.post(
        "/api/v1/datasets/upload",
        files={"file": ("bad.csv", io.BytesIO(content), "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "schema_error"


def test_forecast_returns_full_contract(client, transactions):
    token = _upload(client, transactions).json()["token"]
    response = client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Widget A",
        "horizon_days": 14, "model": "seasonal-naive", "include_backtest": True,
    })
    assert response.status_code == 200
    payload = response.json()

    assert len(payload["forecast"]) == 14
    assert payload["model_info"]["name"] == "seasonal-naive"
    assert payload["data_quality"]["level"] in {"good", "adequate", "limited"}
    assert payload["backtest"]["windows"] >= 1
    assert payload["fusion"]["mode"] in {"unavailable", "disabled", "prior", "calibrated"}
    assert payload["insights"]["cards"]
    assert payload["timings_ms"]["total"] >= 0

    for point in payload["forecast"]:
        assert point["predicted_units"] >= 0
        assert point["lower_80"] <= point["upper_80"]
        assert "base_units" in point


def test_forecast_without_sentiment_reports_fusion_unavailable(client, transactions):
    token = _upload(client, transactions).json()["token"]
    payload = client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Widget A", "horizon_days": 7,
        "model": "seasonal-naive", "include_backtest": False,
    }).json()

    assert payload["fusion"]["applied"] is False
    assert payload["fusion"]["mode"] == "unavailable"
    # The base forecast must equal the served forecast when nothing was fused.
    for point in payload["forecast"]:
        assert point["predicted_units"] == pytest.approx(point["base_units"])


def test_forecast_refuses_short_series(client, transactions):
    short = transactions[transactions["Date"] < "2023-01-16"]
    token = _upload(client, short, "short.csv").json()["token"]

    response = client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Widget A",
        "horizon_days": 30, "model": "seasonal-naive",
    })
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "insufficient_data"
    assert error["details"]["observations"] < 30


def test_unknown_product_returns_suggestions(client, transactions):
    token = _upload(client, transactions).json()["token"]
    response = client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Nonexistent", "model": "seasonal-naive",
    })
    assert response.status_code == 404
    assert response.json()["error"]["details"]["suggestions"]


def test_unknown_model_returns_503(client, transactions):
    token = _upload(client, transactions).json()["token"]
    response = client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Widget A", "model": "gpt-forecaster",
    })
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"


def test_horizon_is_validated(client, transactions):
    token = _upload(client, transactions).json()["token"]
    response = client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Widget A", "horizon_days": 5000,
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_expired_upload_token_is_reported_clearly(client):
    response = client.post("/api/v1/forecast", json={
        "dataset": "upload:deadbeef", "product_name": "Widget A",
    })
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


def test_forecast_run_is_persisted(client, transactions):
    token = _upload(client, transactions).json()["token"]
    client.post("/api/v1/forecast", json={
        "dataset": token, "product_name": "Widget A", "horizon_days": 7,
        "model": "seasonal-naive", "include_backtest": False,
    })

    runs = client.get("/api/v1/runs?limit=5").json()
    assert runs
    assert runs[0]["product_name"] == "Widget A"
    assert runs[0]["model"] == "seasonal-naive"


def test_connectors_endpoint_describes_configuration(client):
    payload = client.get("/api/v1/social/connectors").json()
    names = {connector["name"] for connector in payload["connectors"]}
    assert {"news", "hackernews", "reddit", "trends", "instagram", "x"} <= names
    # Mastodon was removed: it answered Indian apparel queries with unrelated
    # Japanese posts, and its relevance could not be scoped to a market.
    assert "mastodon" not in names
    assert "sentiment_model" in payload


def test_upload_convenience_endpoint(client, transactions):
    content = transactions.to_csv(index=False).encode()
    response = client.post(
        "/api/v1/forecast/upload",
        files={"file": ("t.csv", io.BytesIO(content), "text/csv")},
        data={"product_name": "Widget B", "horizon_days": "7",
              "model": "seasonal-naive", "include_backtest": "false"},
    )
    assert response.status_code == 200
    assert len(response.json()["forecast"]) == 7
