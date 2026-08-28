"""RetailIQ as an MCP server: the service layer, exposed as agent tools.

Why this exists now rather than in Phase 2
------------------------------------------
Phase 2 is an agentic chatbot with sub-agents routed by intent -- sales questions
to one, trend questions to another. Those agents need a tool surface, and the
worst way to build one is to have them make HTTP calls back into our own API and
re-parse their own JSON. So the tool surface is defined here, once, in terms of
the service layer, and both the chatbot and any external MCP client (Claude
Desktop, Claude Code) use the same one.

It is also immediately useful on its own: with this running, you can ask Claude
"which product is falling fastest this month?" and it will query the real data.

The honesty invariants come along unchanged
-------------------------------------------
Every tool here calls the same service functions the HTTP API calls. A series
under the minimum still refuses; social results still carry their provenance;
covariates are still measured rather than assumed. An agent cannot obtain a
softer answer than the dashboard gives, which is the entire reason the business
logic lives in the service layer and not in route handlers.

Running it
----------
    cd backend && .venv/bin/python -m app.mcp_server

Then register it with an MCP client. For Claude Code:

    claude mcp add retailiq -- /absolute/path/to/backend/.venv/bin/python \\
        -m app.mcp_server
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

from app import __version__
from app.config import get_settings
from app.core.errors import AppError
from app.db.session import init_db, session_scope
from app.services import datasets
from app.services.forecast_service import generate_forecast, summarise_products
from app.services.forecasting.registry import list_models

LOG = logging.getLogger(__name__)

INSTRUCTIONS = """
RetailIQ forecasts retail demand from real transaction history.

Start with `list_datasets` to see what data is available, then `list_products`
to see what is in one. `get_forecast` produces a forecast with a rolling-origin
backtest attached, so you can always tell the caller how accurate it is rather
than presenting a number without context.

Three behaviours to expect and pass on faithfully:

* A series shorter than the configured minimum returns an `insufficient_data`
  error. That is deliberate. Report it; do not work around it by shortening the
  horizon or by estimating.
* `lower_95`/`upper_95` are frequently null, because the model's quantile heads
  are trained on 0.1-0.9 only. Null means "not known", not zero.
* Social results carry a `provenance` field (live/cache/fixture/none). Always
  say which one you are quoting.
"""

server = MCPServer(
    name="retailiq",
    title="RetailIQ demand intelligence",
    version=__version__,
    instructions=INSTRUCTIONS,
)


def _error(exc: Exception) -> dict[str, Any]:
    """Surface a typed application error as data an agent can reason about."""
    if isinstance(exc, AppError):
        return {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    LOG.exception("MCP tool failed")
    return {"error": {"code": "internal_error", "message": str(exc)}}


@server.tool(
    title="List datasets",
    description="Every dataset available: bundled samples, uploads, and synced "
                "connections to a retailer's own Shopify or Zoho.",
)
def list_datasets() -> dict[str, Any]:
    try:
        available = datasets.list_connected() + datasets.list_bundled()
    except Exception as exc:
        return _error(exc)
    return {
        "datasets": [
            {
                "id": summary.name,
                "source": summary.source,
                "rows": summary.rows,
                "products": summary.products,
                "first_date": summary.first_date,
                "last_date": summary.last_date,
                "span_days": summary.span_days,
                "description": summary.description,
            }
            for summary in available
        ]
    }


@server.tool(
    title="List products",
    description="Products in a dataset with their history length and a data-quality "
                "grade. Products graded 'insufficient' cannot be forecast.",
)
def list_products(dataset: str = "online-retail-ii") -> dict[str, Any]:
    try:
        resolved = datasets.resolve(dataset)
        products = summarise_products(resolved)
    except Exception as exc:
        return _error(exc)
    return {
        "dataset": dataset,
        "products": [
            {
                "name": product["product_name"],
                "category": product.get("category"),
                "observations": product["observations"],
                "total_units": product["total_units"],
                "first_date": product["first_date"],
                "last_date": product["last_date"],
                # "insufficient" here means get_forecast will refuse this product.
                "data_quality": product["data_quality"],
            }
            for product in products
        ],
    }


@server.tool(
    title="Query sales history",
    description="Daily units sold for one product, optionally within a date range. "
                "Observed history only -- no forecast. Days inside the observed window "
                "with no sales are real zero-demand days and are reported as 0; no day "
                "outside that window is invented.",
)
def query_sales(
    product_name: str,
    dataset: str = "online-retail-ii",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 400,
) -> dict[str, Any]:
    import pandas as pd

    from app.services.series import assess_quality, build_daily_series

    try:
        resolved = datasets.resolve(dataset)
        series = build_daily_series(resolved, product_name)
    except Exception as exc:
        return _error(exc)

    if start_date:
        series = series[series.index >= pd.Timestamp(start_date)]
    if end_date:
        series = series[series.index <= pd.Timestamp(end_date)]
    if series.empty:
        return {
            "product_name": product_name, "dataset": dataset, "observations": 0,
            "returned": 0, "truncated": False, "total_units": 0.0, "series": [],
            "note": "No observations fall inside that date range.",
        }

    quality = assess_quality(series)
    window = series.tail(limit)
    return {
        "product_name": product_name,
        "dataset": dataset,
        "observations": int(series.size),
        "returned": int(window.size),
        "truncated": bool(series.size > window.size),
        "first_date": series.index.min().strftime("%Y-%m-%d"),
        "last_date": series.index.max().strftime("%Y-%m-%d"),
        "total_units": float(series.sum()),
        "data_quality": quality.model_dump(mode="json"),
        "series": [
            {"date": stamp.strftime("%Y-%m-%d"), "units": float(value)}
            for stamp, value in window.items()
        ],
    }


@server.tool(
    title="Forecast demand",
    description="Forecast one product, with a rolling-origin backtest and measured "
                "covariate selection. Refuses series shorter than the configured "
                "minimum rather than padding them.",
)
def get_forecast(
    product_name: str,
    dataset: str = "online-retail-ii",
    horizon_days: int = 30,
    model: str | None = None,
    include_backtest: bool = True,
    include_covariates: bool = True,
) -> dict[str, Any]:
    try:
        resolved = datasets.resolve(dataset)
        with session_scope() as session:
            response = generate_forecast(
                resolved,
                product_name=product_name,
                horizon=horizon_days,
                model_name=model,
                run_backtest_flag=include_backtest,
                use_covariates=include_covariates,
                # An agent wants the numbers; it writes its own prose.
                include_brief=False,
                session=session,
            )
    except Exception as exc:
        return _error(exc)

    payload = response.model_dump(mode="json")
    # History can run to hundreds of points and an agent rarely needs all of it.
    payload["history"] = payload["history"][-90:]
    payload["history_truncated"] = len(response.history) > 90
    return payload


@server.tool(
    title="Explain a forecast",
    description="The plain-English owner brief for a forecast: headline, actions, and "
                "the measured drivers behind it. Every figure is checked against the "
                "computed data before it is returned.",
)
def explain_forecast(
    product_name: str,
    dataset: str = "online-retail-ii",
    horizon_days: int = 30,
) -> dict[str, Any]:
    try:
        resolved = datasets.resolve(dataset)
        with session_scope() as session:
            response = generate_forecast(
                resolved,
                product_name=product_name,
                horizon=horizon_days,
                run_backtest_flag=True,
                use_covariates=True,
                include_brief=True,
                session=session,
            )
    except Exception as exc:
        return _error(exc)

    brief = response.brief or {}
    return {
        "product_name": product_name,
        "horizon_days": horizon_days,
        "brief": brief.get("brief"),
        # Which produced the text, and whether the guard rejected an LLM attempt.
        "source": brief.get("source"),
        "guard_flags": brief.get("guard_flags", []),
        "covariates": response.covariates.model_dump(mode="json"),
        "accuracy": response.backtest.model_dump(mode="json") if response.backtest else None,
    }


@server.tool(
    title="Run the social agent",
    description="Harvest public discussion about a product across the configured "
                "sources and score its sentiment. The result names every source "
                "tried and what each returned, including the ones that failed.",
)
async def run_social_agent(query: str, lookback_days: int = 30) -> dict[str, Any]:
    from app.services.social.agent import analyse

    try:
        with session_scope() as session:
            response = await analyse(query, session, lookback_days)
    except Exception as exc:
        return _error(exc)

    payload = response.model_dump(mode="json")
    # Individual documents are bulky; the top few carry the argument.
    payload["top_documents"] = payload["top_documents"][:6]
    return payload


@server.tool(
    title="List forecasting models",
    description="The models available and which of them accept covariates.",
)
def list_forecasting_models() -> dict[str, Any]:
    settings = get_settings()
    return {
        "default": settings.default_model,
        "device": settings.resolve_device(),
        "models": list_models(),
    }


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    init_db()
    # stdio: the client launches this process and speaks over the pipe. No port,
    # no auth surface, nothing listening on the network.
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
