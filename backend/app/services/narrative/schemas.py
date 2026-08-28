"""Typed contract for the plain-English insight layer.

The LLM is constrained to this schema rather than asked for free prose. Two reasons:
the output is directly renderable by the UI without parsing, and a model that must
fill named fields drifts far less than one asked to "explain the forecast".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "watch", "urgent"]


class Finding(BaseModel):
    """One thing the owner should know, in their language."""

    text: str = Field(description="One sentence, no jargon, no statistics vocabulary")
    severity: Severity = "info"


class Action(BaseModel):
    """Something the owner can actually do this week."""

    text: str
    urgency: Severity = "info"


class Driver(BaseModel):
    """A measured cause behind the forecast, phrased for a non-analyst."""

    label: str
    effect: str = Field(description="Plain-English effect, e.g. 'pushes demand up'")
    detail: str = ""


class OwnerBrief(BaseModel):
    """The 'explain it to a shop owner' view of a forecast."""

    headline: str = Field(
        description="One sentence a busy owner could read and act on"
    )
    summary: str = Field(description="Two or three sentences of context")
    findings: list[Finding] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    drivers: list[Driver] = Field(default_factory=list)
    confidence_note: str = Field(
        default="",
        description="How much to trust this, in plain words, based on the backtest",
    )


class BriefEnvelope(BaseModel):
    """The brief plus its provenance.

    ``source`` matters as much as the text: a template brief is a rendering of
    measured numbers and cannot hallucinate, whereas an LLM brief is an
    interpretation. The UI labels them differently.
    """

    brief: OwnerBrief
    source: Literal["llm", "template", "none"] = "template"
    model: str | None = None
    generated_ms: int = 0
    guard_flags: list[str] = Field(
        default_factory=list,
        description="Numbers the model produced that were not in the input payload",
    )
    warnings: list[str] = Field(default_factory=list)


class ChartExplanation(BaseModel):
    """A short answer to 'what am I looking at?' for one specific chart."""

    chart: str
    text: str
    source: Literal["llm", "template", "none"] = "template"


class SocialBrief(BaseModel):
    """The 'what is being said about this product' view, for the same reader.

    Deliberately mirrors :class:`OwnerBrief`, so the social page and the forecast
    page read as one product rather than two tools bolted together. It carries one
    extra field the forecast brief does not need: ``evidence_note``, because social
    evidence is frequently thin and how much to trust it is the first thing a
    reader needs to know.
    """

    headline: str = Field(description="One sentence on the mood around this product")
    summary: str = Field(description="Two or three sentences of context")
    findings: list[Finding] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    evidence_note: str = Field(
        default="",
        description="How much evidence this rests on and which sources it came from",
    )


class SocialBriefEnvelope(BaseModel):
    brief: SocialBrief
    source: Literal["llm", "template", "none"] = "template"
    model: str | None = None
    generated_ms: int = 0
    guard_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
