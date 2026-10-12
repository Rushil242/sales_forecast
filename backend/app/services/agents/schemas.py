"""Contracts for the assistant.

Two ideas carry the design.

**Facts are separate from prose.** A sub-agent returns structured ``facts`` and a
list of ``Citation``s; nothing it returns is a sentence written for a human. The
writer turns facts into prose as a final, separate step. That separation is what
lets the same answer be rendered by Gemini or by a deterministic template without
either one being able to introduce a number the tools did not produce.

**Every step is inspectable.** ``AgentTrace`` records what the router decided,
which tools ran, and how long each took, and it is streamed to the client while
the work happens. A reviewer watching the demo sees the actual plan, not a
spinner claiming one exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "forecast",       # "how many will I sell next month"
    "sales_history",  # "how did it do last month", "what is falling fastest"
    "social",         # "what are people saying", "is it trending"
    "accuracy",       # "how accurate is this", "how good is the model"
    "catalogue",      # "what products do I have", "what data is connected"
    "capability",     # "what can you do"
    "unsupported",    # honestly out of scope
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Citation(BaseModel):
    """Where one part of an answer came from.

    Invariant 4 (no unattributed numbers) applied to conversation: any figure the
    assistant says must be traceable to a tool result, and the UI shows the trail.
    """

    label: str = Field(description="Human-readable source, e.g. 'Forecast run 3f2a'")
    kind: Literal["forecast", "sales", "social", "dataset", "model", "backtest"]
    detail: str = ""
    # Provenance for social answers: live / cache / fixture / none.
    provenance: str | None = None


class ToolInvocation(BaseModel):
    """One tool call, recorded whether it succeeded or not."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    duration_ms: int = 0
    # Populated only on failure, and surfaced to the user rather than swallowed.
    error: str | None = None


class Entities(BaseModel):
    """What the router managed to resolve out of the message.

    ``product_confidence`` matters: a fuzzy match at 0.55 against a catalogue of
    thirty products is a guess, and the assistant says so rather than silently
    answering about the wrong product.
    """

    product: str | None = None
    product_confidence: float = 0.0
    dataset: str | None = None
    horizon_days: int | None = None
    lookback_days: int | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    # Set when the entity came from the previous turn rather than this message.
    carried_over: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    intent: Intent
    confidence: float
    # Why this intent won, in words -- shown in the trace so routing is auditable.
    reason: str
    entities: Entities = Field(default_factory=Entities)
    # True when the deterministic router was unsure and an LLM broke the tie.
    escalated: bool = False


class AgentTrace(BaseModel):
    """The run log the UI renders while the answer is being produced."""

    route: RouteDecision
    agent: str
    tools: list[ToolInvocation] = Field(default_factory=list)
    total_ms: int = 0


class ChatAnswer(BaseModel):
    """One assistant turn.

    ``source`` says who wrote the prose: ``llm`` means Gemini phrased it and the
    number guard passed it; ``template`` means it was composed directly from the
    facts. Both are honest; the badge tells the reader which they are looking at,
    exactly as the forecast and social briefs already do.
    """

    answer: str
    follow_ups: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    trace: AgentTrace
    facts: dict[str, Any] = Field(default_factory=dict)
    source: Literal["llm", "template"] = "template"
    guard_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class AgentResult(BaseModel):
    """What a sub-agent hands back to the orchestrator. Facts, never prose."""

    facts: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    tools: list[ToolInvocation] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # A refusal is a legitimate outcome, not an error: too little history, no
    # product resolved, a source that would not answer. The writer renders it.
    refusal: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Prior turns, so "and what about next month?" resolves. Trimmed server-side.
    history: list[ChatMessage] = Field(default_factory=list)
    dataset: str | None = None
    # Carried entities from the last turn, so follow-ups need no repetition.
    context: Entities | None = None
