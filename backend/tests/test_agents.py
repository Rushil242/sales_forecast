"""The assistant: routing, entity resolution, and the guarantees it inherits.

The tests that matter most here are the ones asserting the assistant is *not* a
softer door. A product with too little history must be refused in conversation
exactly as it is refused over HTTP and over MCP, and an answer must never contain
a figure the tools did not produce.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.services.agents import composer, router
from app.services.agents.entities import (
    extract_horizon,
    extract_lookback,
    resolve,
    resolve_product,
)
from app.services.agents.schemas import AgentResult
from app.services.narrative import guard

CATALOGUE = [
    "Printed A-Line Kurti",
    "Oversized Cotton Tee",
    "Rayon Crop Top",
    "Linen Blend Casual Shirt",
    "Pique Polo T-Shirt",
    "Straight Fit Denim Jeans",
]


# ── entity resolution ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("how many kurtis will i sell next month", "Printed A-Line Kurti"),
        ("what about the crop top", "Rayon Crop Top"),
        ("forecast denim jeans for the next 60 days", "Straight Fit Denim Jeans"),
        ("what are people saying about the oversized cotton tee", "Oversized Cotton Tee"),
    ],
)
def test_products_resolve_from_how_people_actually_type(message, expected):
    """Nobody types the full SKU name. 'kurtis' has to reach 'Printed A-Line Kurti'."""
    product, score = resolve_product(message, CATALOGUE)
    assert product == expected
    assert score > 0.5


def test_a_question_about_no_particular_product_resolves_to_none():
    """'Which product is falling fastest' is about all of them, not one of them."""
    product, score = resolve_product("which product is falling fastest", CATALOGUE)
    assert product is None
    assert score == 0.0


@pytest.mark.parametrize(
    ("message", "days"),
    [
        ("forecast it for the next 60 days", 60),
        ("how many will i sell next month", 30),
        ("what about the coming week", 7),
        ("give me the next quarter", 90),
    ],
)
def test_horizons_are_read_from_ordinary_english(message, days):
    assert extract_horizon(message) == days


def test_a_backward_looking_window_is_not_read_as_a_horizon():
    """'in the last 30 days' asks about history, not about the next 30 days."""
    assert extract_lookback("how did it do in the last 30 days") == 30
    assert extract_horizon("how did it do in the last 30 days") is None


def test_entities_carry_over_so_follow_ups_work():
    """'And what about next month?' has to remember what 'it' was."""
    first = resolve("how did the crop top do", CATALOGUE)
    assert first.product == "Rayon Crop Top"

    second = resolve("and what about next month", CATALOGUE, carried=first)
    assert second.product == "Rayon Crop Top"
    # Named explicitly, so the answer can admit which product it assumed.
    assert "product" in second.carried_over


# ── routing ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("how many kurtis will i sell next month", "forecast"),
        ("what are people saying about the crop top", "social"),
        ("how accurate is that forecast", "accuracy"),
        ("which product is falling fastest", "sales_history"),
        ("what products do i have", "catalogue"),
        ("what can you do", "capability"),
        ("is the kurti trending on instagram", "social"),
        ("how did denim jeans do last month", "sales_history"),
    ],
)
def test_intents_route_without_an_llm_call(message, intent):
    """Routing is lexical on purpose: no latency, no quota, works offline."""
    decision = router.route(message, CATALOGUE)
    assert decision.intent == intent
    assert decision.confidence > 0.5
    # The reason is shown in the UI, so it must actually say something.
    assert decision.reason


def test_a_bare_product_name_is_read_as_a_demand_question():
    decision = router.route("Rayon Crop Top", CATALOGUE)
    assert decision.intent == "forecast"
    assert decision.entities.product == "Rayon Crop Top"


def test_routing_reports_low_confidence_rather_than_guessing_silently():
    decision = router.route("hmm", CATALOGUE)
    assert decision.confidence < 0.5


# ── the guarantees ────────────────────────────────────────────────────────────

def test_the_template_answer_invents_no_figure():
    """Whatever the composer writes must survive the same guard the LLM faces."""
    facts = {
        "product": "Rayon Crop Top",
        "horizon_days": 30,
        "total_predicted_units": 985.0,
        "mean_predicted_units_per_day": 32.8,
        "total_upper_80": 1420.0,
        "peak_day": {"date": "2026-09-08", "units": 53.3},
        "covariates_kept": ["holiday"],
        "covariates_rejected": ["weather", "calendar"],
        "accuracy": {"mase": 0.542, "windows": 5, "horizon": 30,
                     "improvement_over_naive_pct": 38.4, "coverage_80": 0.81,
                     "best_model": "chronos-2"},
    }
    decision = router.route("how many crop tops will i sell next month", CATALOGUE)
    text = composer.render("", decision, AgentResult(facts=facts))

    assert guard.check(text, facts) == []


def test_the_template_answer_uses_no_statistics_vocabulary():
    """The reader was promised plain English; the template must honour it too.

    This caught a real regression: the accuracy renderer said "seasonal-naive
    baseline" while the guard was rejecting the model for the same phrase.
    """
    facts = {
        "product": "Rayon Crop Top",
        "accuracy": {"mase": 1.184, "windows": 4, "horizon": 30,
                     "improvement_over_naive_pct": 10.4, "coverage_80": 0.93,
                     "best_model": "chronos-2",
                     "baselines": [{"model": "chronos-2", "mase": 1.184},
                                   {"model": "theta", "mase": 1.5}]},
    }
    decision = router.route("how accurate is that", CATALOGUE)
    text = composer.render("", decision, AgentResult(facts=facts))

    assert guard.check_jargon(text) == []


def test_a_refusal_is_the_answer_not_an_error():
    """Too little history is a correct outcome, relayed in the owner's words."""
    refusal = (
        "'Zara Mens' does not have enough sales history to forecast honestly."
    )
    decision = router.route("forecast zara mens", CATALOGUE)
    text = composer.render("", decision, AgentResult(refusal=refusal))
    assert text == refusal


@pytest.mark.parametrize(
    "suggestion",
    [
        "Show me the forecast for [product name]",
        "Compare <your product> to another",
        "Can you give me a forecast for product X?",
        "What is the public saying about product Y?",
        "What are people saying about your product?",
    ],
)
def test_placeholder_follow_ups_are_dropped(suggestion):
    """A suggestion the user cannot click is worse than no suggestion.

    Measured live: with no product in context the model offers "forecast for
    product X", which reads like a question and names nothing.
    """
    assert composer._PLACEHOLDER.search(suggestion)


@pytest.mark.parametrize(
    "suggestion",
    [
        "Forecast Rayon Crop Top for 30 days",
        "What products are available?",
        "How did the Pique Polo T-Shirt sell?",
    ],
)
def test_real_follow_ups_are_kept(suggestion):
    assert not composer._PLACEHOLDER.search(suggestion)


def test_the_jargon_guard_catches_what_the_prompt_only_requests():
    """Gemini was measured writing 'MASE' despite being told not to."""
    assert "mase" in guard.check_jargon("The forecast has a MASE of 1.184.")
    assert guard.check_jargon("It sold 1,240 units, about 41 a day.") == []


# ── the refusal survives the conversational path ──────────────────────────────

@pytest.mark.anyio
async def test_the_refusal_survives_the_assistant_path(tiny_dataset, monkeypatch):
    """A short series must refuse in chat exactly as it does over HTTP and MCP.

    The whole point of putting business logic in the service layer is that no
    surface can offer a softer answer than another. A chatbot is the surface
    most likely to try, because a conversational refusal feels impolite -- so it
    is the one worth pinning with a test.
    """
    from app.services import datasets as registry
    from app.services.agents import orchestrator
    from app.services.agents.schemas import ChatRequest

    monkeypatch.setattr(registry, "resolve", lambda identifier: tiny_dataset)
    monkeypatch.setattr(orchestrator, "product_catalogue", lambda _: ["Widget"])
    # Force the deterministic path: the assertion is about the refusal, not
    # about whatever Gemini would have said around it.
    monkeypatch.setattr(
        "app.services.narrative.client.generate_chat_answer", lambda *a, **k: None
    )

    result = await orchestrator.answer(
        ChatRequest(message="forecast Widget for the next 30 days", dataset="tiny")
    )

    assert result.trace.route.intent == "forecast"
    assert "enough sales history" in result.answer
    # And it says why rather than dressing the refusal up as a small number.
    assert "invent" in result.answer.lower() or "pad" in result.answer.lower()


@pytest.fixture
def tiny_dataset():
    """Fifteen days: real, and deliberately below the thirty-day minimum."""
    from app.services.ingestion import Dataset

    dates = pd.date_range("2026-01-01", periods=15, freq="D")
    frame = pd.DataFrame({
        "date": dates,
        "product": ["Widget"] * 15,
        "units": [3.0] * 15,
    })
    return Dataset(name="tiny", frame=frame, column_map={
        "date": "date", "product": "product", "units": "units",
    })
