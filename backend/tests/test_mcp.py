"""MCP server smoke tests.

The property worth guarding is that the agent surface is not a softer door. An
agent asking to forecast a 15-day series must be refused exactly as the dashboard
is refused, and told *why* in a form it can act on -- not handed a padded answer
because it came in through a different entrance.

These run against uploaded fixtures rather than the bundled CSV, because the test
suite points ``data_dir`` at a throwaway directory.
"""

from __future__ import annotations

import json

import pytest

from app.mcp_server import server
from app.services import datasets


async def call(name: str, arguments: dict | None = None) -> dict:
    """Invoke a tool and return its payload the way an MCP client would see it."""
    result = await server.call_tool(name, arguments or {})
    structured = getattr(result, "structured_content", None)
    if structured:
        return structured
    return json.loads(result.content[0].text)


@pytest.fixture
def uploaded(transactions):
    """The 400-day synthetic dataset, registered so tools can resolve it by token."""
    token, _ = datasets.store_upload(
        transactions.to_csv(index=False).encode(), "mcp-test.csv"
    )
    yield token
    datasets._upload_cache.pop(token, None)


@pytest.fixture
def uploaded_short(transactions):
    """Fifteen days, the length that must be refused."""
    frame = transactions[transactions["Date"] < "2023-01-16"]
    token, _ = datasets.store_upload(frame.to_csv(index=False).encode(), "short.csv")
    yield token
    datasets._upload_cache.pop(token, None)


@pytest.mark.asyncio
async def test_the_tool_surface_is_the_one_phase_two_will_use():
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert {
        "list_datasets", "list_products", "query_sales",
        "get_forecast", "explain_forecast", "run_social_agent",
    } <= names
    # An agent picks tools by their description, so an undescribed tool is unusable.
    assert all(tool.description for tool in tools)


@pytest.mark.asyncio
async def test_products_are_listable_with_their_data_quality(uploaded):
    payload = await call("list_products", {"dataset": uploaded})
    assert {p["name"] for p in payload["products"]} == {"Widget A", "Widget B"}
    assert {"name", "observations", "data_quality"} <= set(payload["products"][0])


@pytest.mark.asyncio
async def test_query_sales_returns_observed_history_only(uploaded):
    payload = await call("query_sales", {
        "dataset": uploaded, "product_name": "Widget A", "limit": 10,
    })
    assert payload["returned"] == 10
    assert payload["truncated"] is True
    assert payload["observations"] == 400
    assert payload["data_quality"]["level"] in {"good", "adequate", "limited", "insufficient"}
    # The window ends where the data ends; nothing is projected forward.
    assert payload["series"][-1]["date"] == payload["last_date"]


@pytest.mark.asyncio
async def test_query_sales_honours_a_date_range(uploaded):
    payload = await call("query_sales", {
        "dataset": uploaded, "product_name": "Widget A",
        "start_date": "2023-02-01", "end_date": "2023-02-28",
    })
    assert payload["observations"] == 28
    assert payload["first_date"] == "2023-02-01"


@pytest.mark.asyncio
async def test_an_unknown_product_returns_a_typed_error_with_suggestions(uploaded):
    payload = await call("query_sales", {
        "dataset": uploaded, "product_name": "Widget Z",
    })
    assert payload["error"]["code"] == "product_not_found"
    assert "suggestions" in payload["error"]["details"]


@pytest.mark.asyncio
async def test_the_refusal_survives_the_agent_path(uploaded_short):
    """Fifteen days is refused through MCP exactly as it is through HTTP."""
    payload = await call("get_forecast", {
        "dataset": uploaded_short, "product_name": "Widget A",
        "horizon_days": 30, "include_covariates": False,
    })
    assert payload["error"]["code"] == "insufficient_data"
    assert payload["error"]["message"]


@pytest.mark.asyncio
async def test_a_real_forecast_carries_its_own_accuracy(uploaded):
    payload = await call("get_forecast", {
        "dataset": uploaded, "product_name": "Widget A", "horizon_days": 7,
        "model": "seasonal-naive", "include_backtest": True, "include_covariates": False,
    })
    assert "error" not in payload
    assert len(payload["forecast"]) == 7
    assert payload["backtest"]["metrics_by_model"]
    # History is trimmed for the agent, and it says so rather than letting the
    # agent believe the series is only 90 days long.
    assert len(payload["history"]) == 90
    assert payload["history_truncated"] is True


@pytest.mark.asyncio
async def test_an_unknown_dataset_is_an_error_not_a_default(uploaded):
    payload = await call("list_products", {"dataset": "upload:deadbeef"})
    assert payload["error"]["code"] == "dataset_not_found"
