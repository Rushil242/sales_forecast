"""Gemini client for the plain-English insight layer.

Why the data and not a picture of the data
------------------------------------------
The obvious way to "explain a chart with AI" is to screenshot the chart and hand it
to a vision model. That is strictly worse here. We already hold every value behind
every pixel -- the forecast points, the interval bounds, the backtest metrics, the
covariate deltas. Sending an image throws that precision away and asks the model to
re-read numbers it could have been given exactly, which is how chart explanations end
up misreading axes and inventing trends.

So the payload is the computed statistics, and the model's job is translation rather
than perception. The structure follows Microsoft LIDA's summarizer pattern: compact
the data into a natural-language-ready summary, then narrate it.

Everything the model returns passes through ``guard.py`` before it reaches a user.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache

from app.config import get_settings
from app.services.narrative import guard
from app.services.narrative.schemas import (
    BriefEnvelope,
    ChartExplanation,
    OwnerBrief,
    SocialBrief,
    SocialBriefEnvelope,
)

LOG = logging.getLogger(__name__)

SYSTEM_PROMPT = """You explain retail demand forecasts to shop owners and inventory \
managers. They are smart about their business and not about statistics.

Rules, in order of importance:

1. NEVER state a number that is not present in the data you were given. Do not \
estimate, round to a "nicer" figure, or infer a statistic. If you want to say \
something you have no number for, say it qualitatively instead.
2. No statistics vocabulary. Never write MASE, RMSE, quantile, confidence interval, \
covariate, or p-value. Say "how accurate this has been", "the likely range", \
"what we checked".
3. Write for someone deciding how much stock to buy this month.
4. Be direct about uncertainty. If the data is thin or the model was not much better \
than guessing, say so plainly in confidence_note.
5. Every action must be something they could do this week.

Currency and units: the data is in units sold, not money. Do not invent prices.
6. Format numbers the way a person writes them: thousands separators \
(5,720 not 5720), at most one decimal place, and "%" not the word "percent". \
Never print a raw decimal like 5720.7 -- round it and keep the separator."""

CHART_PROMPT = """You explain one chart from a retail forecasting dashboard to a shop \
owner. Two or three sentences. No statistics vocabulary. Never state a number that is \
not in the data provided. Say what the chart shows and what it means for their stock \
decisions."""


@lru_cache(maxsize=1)
def _client():
    """One cached client for the process.

    Building a fresh one per call looked harmless but was not: in
    ``_client().models.generate_content(...)`` the Client is unreferenced the
    moment ``.models`` is read, so it could be garbage-collected mid-request --
    google-genai closes its underlying httpx transport on finalisation, and the
    call failed with "Cannot send a request, as the client has been closed".
    Holding the reference is the fix; caching it is also simply cheaper.
    """
    from google import genai

    return genai.Client(api_key=get_settings().google_api_key)


def is_available() -> bool:
    settings = get_settings()
    if not settings.narrative_enabled or not settings.has_gemini:
        return False
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return False
    return True


# Why the last call failed, in the owner's language. Without this the UI can only
# say "Computed", which reads as "no key configured" even when the real cause is a
# spent daily quota -- a different problem with a different fix.
_last_failure: str = ""


def _record_failure(exc: Exception) -> None:
    global _last_failure
    text = str(exc)
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        _last_failure = (
            "The Google AI Studio free-tier quota for today is used up, so this brief "
            "was computed from the measured figures rather than written by Gemini. "
            "It resets daily."
        )
    else:
        _last_failure = (
            "Gemini could not be reached, so this brief was computed from the measured "
            f"figures instead ({type(exc).__name__})."
        )


def _record_success() -> None:
    global _last_failure
    _last_failure = ""


def unavailable_reason() -> str:
    settings = get_settings()
    if not settings.narrative_enabled:
        return "The narrative layer is disabled in configuration."
    if not settings.has_gemini:
        return (
            "No Google AI Studio key is set. Add RETAILIQ_GOOGLE_API_KEY to enable "
            "AI-written briefs; the measured template brief is used meanwhile."
        )
    try:
        import google.genai  # noqa: F401
    except ImportError:
        return "The google-genai package is not installed."
    return _last_failure


def generate_brief(payload: dict) -> BriefEnvelope | None:
    """Ask Gemini for an owner-facing brief. ``None`` means the caller should fall back."""
    if not is_available():
        return None

    settings = get_settings()
    started = time.perf_counter()

    try:
        from google.genai import types

        response = _client().models.generate_content(
            model=settings.gemini_model,
            contents=(
                "Here is everything measured about this forecast. Explain it.\n\n"
                + json.dumps(payload, indent=2, default=str)
            ),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=OwnerBrief,
                max_output_tokens=settings.gemini_max_tokens,
                temperature=0.3,
            ),
        )
    except Exception as exc:
        LOG.warning("Gemini brief failed (%s); falling back to the template brief", exc)
        _record_failure(exc)
        return None

    elapsed = int((time.perf_counter() - started) * 1000)

    brief = getattr(response, "parsed", None)
    if brief is None:
        try:
            brief = OwnerBrief.model_validate_json(response.text)
        except Exception as exc:
            LOG.warning("Gemini returned unparsable JSON (%s)", exc)
            return None

    # The guard is the whole reason this can be trusted in a product that claims its
    # numbers are measured. A brief that invents a figure is discarded, not shown.
    flags = guard.check_brief(brief, payload)
    if flags:
        LOG.warning(
            "Discarding Gemini brief: %d unsupported figure(s) -> %s",
            len(flags), ", ".join(flags),
        )
        return BriefEnvelope(
            brief=brief, source="none", model=settings.gemini_model,
            generated_ms=elapsed, guard_flags=flags,
            warnings=[
                "The AI-written brief referenced figures that were not in the measured "
                "data, so it was discarded and the computed brief shown instead."
            ],
        )

    LOG.info("Gemini brief in %d ms (%s)", elapsed, settings.gemini_model)
    return BriefEnvelope(
        brief=brief, source="llm", model=settings.gemini_model, generated_ms=elapsed,
    )


def explain_chart(chart: str, payload: dict) -> ChartExplanation | None:
    """A short plain-English reading of one chart."""
    if not is_available():
        return None

    settings = get_settings()
    try:
        from google.genai import types

        response = _client().models.generate_content(
            model=settings.gemini_model,
            contents=(
                f"Chart: {chart}\n\nData behind it:\n"
                + json.dumps(payload, indent=2, default=str)
            ),
            config=types.GenerateContentConfig(
                system_instruction=CHART_PROMPT,
                max_output_tokens=400,
                temperature=0.3,
            ),
        )
        text = (response.text or "").strip()
    except Exception as exc:
        LOG.warning("Gemini chart explanation failed: %s", exc)
        return None

    if not text:
        return None

    flags = guard.check(text, payload)
    if flags:
        LOG.warning("Chart explanation flagged for %s: %s", chart, ", ".join(flags))
        return None

    return ChartExplanation(chart=chart, text=text, source="llm")


SOCIAL_PROMPT = """You brief a shop owner on what people are saying about one of \
their products online. They are smart about their business and not about statistics.

Rules, in order of importance:

1. NEVER state a number that is not present in the data you were given. Do not \
estimate or round to a nicer figure. If you have no number for something, say it \
qualitatively.
2. The evidence is often thin. If few documents were found, or most sources returned \
nothing, lead with that rather than burying it. An owner acting on twelve posts \
should know it was twelve.
3. No jargon. Never write sentiment score, engagement rate, corpus, or n=. Say \
"people are broadly positive", "one post did most of the talking".
4. Search interest is attention, not approval. Never describe Google Trends numbers \
as positive or negative sentiment.
5. Every action must be something they could do this week, and must follow from the \
evidence. If the evidence supports no action, say that instead of inventing one.
6. Write FOUR to SIX findings, not one. Each must be a specific, concrete \
observation a buyer could act on -- name the platform, the word people keep using, \
the day it spiked, the split between audiences.
7. Write each finding as a sentence you would SAY to the owner across a counter, \
not as an analyst's note. "Sentiment is mixed" and "Most-repeated words: kurta (7)" \
are both wrong. Write instead: "People keep pairing this with the word 'festive', \
and those posts are positive -- it is being bought as occasion wear." Lead with the \
thing that happened, then what it means for their buying.
8. Say WHY when, and only when, the posts themselves say why. You are given the \
text of example posts for exactly this: if several of them mention a festival, a \
launch, cold weather or a well-known person wearing it, name that as the reason. If \
the posts give no reason, say what is happening without inventing a cause. Never \
guess at a cause that is not in the text you were given.
9. Search interest has a change figure (`change_vs_earlier_in_window_pct`). If it \
is meaningful, lead a finding with it in plain words -- "people are searching for \
this X% more than earlier in the month" -- and remember it is curiosity, not approval.
10. Never quote a post that is not in the reader's language, and never paste a long \
raw post into a finding. Describe what it said instead.
11. Format numbers the way a person writes them: thousands separators \
(5,720 not 5720), at most one decimal place, and "%" not the word "percent". \
Never print a raw decimal like 5720.7 -- round it and keep the separator."""


def generate_social_brief(payload: dict) -> SocialBriefEnvelope | None:
    """Ask Gemini to brief the owner on the social picture. ``None`` = fall back."""
    if not is_available():
        return None

    settings = get_settings()
    started = time.perf_counter()

    try:
        from google.genai import types

        response = _client().models.generate_content(
            model=settings.gemini_model,
            contents=(
                "Here is everything measured about the public discussion of this "
                "product. Brief the owner on it.\n\n"
                + json.dumps(payload, indent=2, default=str)
            ),
            config=types.GenerateContentConfig(
                system_instruction=SOCIAL_PROMPT,
                response_mime_type="application/json",
                response_schema=SocialBrief,
                max_output_tokens=settings.gemini_max_tokens,
                temperature=0.3,
            ),
        )
    except Exception as exc:
        LOG.warning("Gemini social brief failed (%s); falling back to the template", exc)
        _record_failure(exc)
        return None

    elapsed = int((time.perf_counter() - started) * 1000)
    brief = getattr(response, "parsed", None)
    if brief is None:
        try:
            brief = SocialBrief.model_validate_json(response.text)
        except Exception as exc:
            LOG.warning("Gemini returned unparsable social JSON (%s)", exc)
            return None

    # Same guard as the forecast brief. A social brief that invents a figure is
    # exactly as damaging as a forecast brief that does.
    flags = guard.check_brief(brief, payload)
    if flags:
        LOG.warning(
            "Discarding Gemini social brief: %d unsupported figure(s) -> %s",
            len(flags), ", ".join(flags),
        )
        return SocialBriefEnvelope(
            brief=brief, source="none", model=settings.gemini_model,
            generated_ms=elapsed, guard_flags=flags,
            warnings=[
                "The AI-written brief referenced figures that were not in the measured "
                "data, so it was discarded and the computed brief shown instead."
            ],
        )

    _record_success()
    LOG.info("Gemini social brief in %d ms (%s)", elapsed, settings.gemini_model)
    return SocialBriefEnvelope(
        brief=brief, source="llm", model=settings.gemini_model, generated_ms=elapsed,
    )
