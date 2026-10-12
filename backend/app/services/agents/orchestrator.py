"""The loop: route, run one sub-agent, write the answer.

Why there is no ReAct loop
--------------------------
The canonical agent design lets a model choose tools, observe results, and choose
again until it decides to stop. That is the right architecture when the space of
useful tool sequences is large and unknowable. Here it is neither: there are four
kinds of question, each answered by a known sequence, and the expensive step
(a forecast with a backtest) takes fifteen seconds. An iterative loop would spend
three model calls and thirty seconds discovering a plan that a router settles in
under a millisecond, and would do it against a 20-request daily quota.

So the plan is chosen deterministically and the model is spent only on the last
step, phrasing. What makes this agentic is not the loop -- it is that the system
decides which capability to invoke, executes real tools against real data,
handles their refusals, and composes an answer from what came back. That decision
and that execution are visible in ``AgentTrace`` rather than asserted.

Where a model genuinely helps -- disambiguating a question the keywords cannot
separate -- the escalation hook is there and is off unless the quota allows it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.services import datasets as dataset_registry
from app.services.agents import composer, router
from app.services.agents.schemas import (
    AgentResult,
    AgentTrace,
    ChatAnswer,
    ChatRequest,
    Entities,
)
from app.services.agents.subagents import catalogue, forecast, sales, social

LOG = logging.getLogger(__name__)

StageFn = Callable[[str, str], None]

# Which sub-agent owns which intent. Keeping this as data rather than an if-chain
# means adding a fifth capability is a one-line change plus a module.
AGENT_FOR_INTENT = {
    "forecast": "forecast",
    "accuracy": "forecast",
    "sales_history": "sales",
    "social": "social",
    "catalogue": "catalogue",
    "capability": "none",
    "unsupported": "none",
}


def _announce(on_stage: StageFn | None, stage: str, detail: str) -> None:
    if on_stage is None:
        return
    try:
        on_stage(stage, detail)
    except Exception:  # a broken listener must never cost the user their answer
        LOG.debug("Progress listener failed at stage %s", stage)


def default_dataset() -> str:
    """Prefer a live connection over a bundled sample.

    Someone who has connected their Shopify store is asking about their store.
    Answering from the bundled UK giftware file would be technically valid and
    completely useless.
    """
    try:
        connected = dataset_registry.list_connected()
        if connected:
            return connected[0].name
    except Exception:
        LOG.debug("Could not list connected datasets; falling back to bundled")
    try:
        bundled = dataset_registry.list_bundled()
        if bundled:
            return bundled[0].name
    except Exception:
        LOG.debug("Could not list bundled datasets")
    return "online-retail-ii"


def product_catalogue(dataset_id: str) -> list[str]:
    """Product names for entity resolution. Empty on failure, never an exception."""
    try:
        return dataset_registry.resolve(dataset_id).products()
    except Exception as exc:
        LOG.warning("Could not read products from %s: %s", dataset_id, exc)
        return []


async def answer(
    request: ChatRequest,
    *,
    session: Any = None,
    on_stage: StageFn | None = None,
) -> ChatAnswer:
    """Run one conversational turn end to end."""
    started = time.perf_counter()
    dataset_id = request.dataset or (
        request.context.dataset if request.context and request.context.dataset else None
    ) or default_dataset()

    _announce(on_stage, "understand", "Reading the question and resolving the product")
    products = product_catalogue(dataset_id)
    decision = router.route(request.message, products, carried=request.context)
    decision.entities.dataset = dataset_id

    agent_name = AGENT_FOR_INTENT.get(decision.intent, "none")
    _announce(
        on_stage, "route",
        f"Routed to the {agent_name} agent — {decision.reason}"
        if agent_name != "none" else "Answering from what this assistant can do",
    )

    result = await _dispatch(
        agent_name, decision, request, dataset_id, session=session, on_stage=on_stage
    )

    # A refusal for want of a product is the one case where the sub-agent has no
    # useful suggestions of its own, and it is exactly the case where naming a
    # real product is most useful. The catalogue is already loaded here.
    if not result.follow_ups and products:
        result.follow_ups = [
            f"Forecast {products[0]} for the next 30 days",
            f"How did {products[1] if len(products) > 1 else products[0]} sell last month?",
            "What products do I have?",
        ]

    _announce(on_stage, "compose", "Writing the answer from the measured figures")
    text, follow_ups, source, flags = composer.compose(request.message, decision, result)

    trace = AgentTrace(
        route=decision,
        agent=agent_name,
        tools=result.tools,
        total_ms=int((time.perf_counter() - started) * 1000),
    )
    return ChatAnswer(
        answer=text,
        follow_ups=follow_ups,
        citations=result.citations,
        trace=trace,
        facts=result.facts,
        source=source,
        guard_flags=flags,
        warnings=result.warnings,
    )


async def _dispatch(
    agent_name: str,
    decision: Any,
    request: ChatRequest,
    dataset_id: str,
    *,
    session: Any,
    on_stage: StageFn | None,
) -> AgentResult:
    """Run the chosen sub-agent, in a worker thread when it blocks."""
    import asyncio

    entities: Entities = decision.entities

    if agent_name == "forecast":
        want_accuracy = decision.intent == "accuracy"
        _announce(
            on_stage, "forecast",
            f"Forecasting {entities.product or 'the selected product'} "
            f"over {entities.horizon_days or forecast.DEFAULT_HORIZON} days, "
            "with a rolling-origin backtest",
        )
        # generate_forecast is CPU-bound and synchronous; running it inline would
        # block the event loop and stall the very SSE stream reporting on it.
        return await asyncio.to_thread(
            forecast.run,
            entities, request.message, dataset_id,
            want_accuracy=want_accuracy,
            on_stage=on_stage,
        )

    if agent_name == "sales":
        _announce(
            on_stage, "sales",
            f"Reading sales history from {dataset_id}"
            + (f" for {entities.product}" if entities.product else " across every product"),
        )
        return await asyncio.to_thread(sales.run, entities, request.message, dataset_id)

    if agent_name == "social":
        _announce(
            on_stage, "social",
            f"Harvesting public discussion about {entities.product or 'the product'} "
            "across every reachable source",
        )
        return await social.run(entities, request.message, session=session)

    if agent_name == "catalogue":
        _announce(on_stage, "catalogue", "Listing datasets, connections and products")
        return await asyncio.to_thread(catalogue.run, entities, request.message)

    return AgentResult()
