"""Turning facts into an answer, with or without a model.

Two renderers, one contract. ``compose`` prefers Gemini and falls back to a
deterministic template, and the caller is told which ran. That is the same
pattern the forecast and social briefs already use, adopted here for a reason
specific to conversation: **the Gemini free tier allows 20 requests per day**.
A chatbot that needs a model call per turn is a chatbot that stops working after
ten questions, and stops working during the demo it was built for.

So the template is not a degraded mode kept around for completeness. It is the
path most turns actually take, and it is written to be good enough to ship on its
own. The model, when it is available, makes the answer read better -- it is not
what makes the answer true.

Nothing here can invent a figure. The template only formats values it was handed;
the model's output is checked against those same values by the number guard and
discarded whole if it strays.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.agents.schemas import AgentResult, Entities, RouteDecision
from app.services.narrative import client

LOG = logging.getLogger(__name__)

# A suggestion the user cannot click, offered because the model had no real name
# to put in it. Two shapes: an explicit slot ("[product name]", "<your product>")
# and the softer stand-in ("product X", "a specific product") that reads like a
# question but names nothing. Both are dropped in favour of the sub-agent's own
# suggestions, which are built from the actual catalogue.
_PLACEHOLDER = re.compile(
    r"[\[<{][^\]>}]{2,40}[\]>}]"
    r"|\bproduct\s+[XYZ]\b"
    r"|\b(?:your|a|the|some|any|specific|another|certain)\s+(?:specific\s+)?product\b"
    r"|\b(?:product|item)\s+name\b",
    re.IGNORECASE,
)


def number(value: Any, places: int = 0) -> str:
    """A figure written the way a person writes it."""
    if value is None:
        return "unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if places == 0:
        return f"{round(numeric):,}"
    return f"{numeric:,.{places}f}"


def signed_pct(value: Any, places: int = 1) -> str:
    if value is None:
        return "unknown"
    numeric = float(value)
    return f"{'+' if numeric >= 0 else ''}{numeric:,.{places}f}%"


def _assumed_product(facts: dict) -> str:
    """Name the product when the match was a guess, so a wrong guess is visible."""
    confidence = facts.get("product_confidence")
    product = facts.get("product")
    if product and confidence is not None and confidence < 0.8:
        return f"Assuming you meant **{product}** — "
    return ""


def compose(
    question: str,
    route: RouteDecision,
    result: AgentResult,
) -> tuple[str, list[str], str, list[str]]:
    """Return ``(answer, follow_ups, source, guard_flags)``.

    The template runs first and unconditionally, so there is always an answer
    even if the model call fails halfway through.
    """
    template_answer = render(question, route, result)
    follow_ups = result.follow_ups[:3]

    payload = dict(result.facts)
    if result.refusal:
        payload["refusal"] = result.refusal

    attempt = client.generate_chat_answer(question, payload)
    if attempt is None:
        return template_answer, follow_ups, "template", []

    reply, flags = attempt
    if flags:
        # The model wrote a number the tools did not produce. Its whole reply is
        # discarded rather than edited: a brief that invented one figure has
        # shown it will invent another.
        LOG.warning("Chat guard rejected an answer over %s", ", ".join(flags))
        return template_answer, follow_ups, "template", flags

    # The model writes follow-ups as templates when it has no concrete product to
    # name -- "Show me the forecast for [product name]" -- which is unclickable
    # and teaches the user the wrong thing to type. The sub-agent's own
    # suggestions are built from real catalogue entries, so they win the tie.
    model_follow_ups = [
        q.strip() for q in (reply.follow_ups or [])
        if q.strip() and not _PLACEHOLDER.search(q)
    ][:3]
    return reply.answer.strip(), (model_follow_ups or follow_ups), "llm", []


def render(question: str, route: RouteDecision, result: AgentResult) -> str:
    """The deterministic answer. Every sentence is a formatted measured value."""
    if result.refusal:
        return result.refusal

    facts = result.facts
    renderer = {
        "forecast": _render_forecast,
        "accuracy": _render_accuracy,
        "sales_history": _render_sales,
        "social": _render_social,
        "catalogue": _render_catalogue,
        "capability": _render_capability,
    }.get(route.intent, _render_capability)
    return renderer(facts, route.entities)


def _render_forecast(facts: dict, entities: Entities) -> str:
    if not facts:
        return _render_capability(facts, entities)

    product = facts.get("product", "this product")
    horizon = facts.get("horizon_days", 30)
    total = facts.get("total_predicted_units")
    per_day = facts.get("mean_predicted_units_per_day")

    parts = [
        f"{_assumed_product(facts)}**{product}** is forecast to sell "
        f"**{number(total, 1)} units** over the next {horizon} days — about "
        f"{number(per_day, 1)} a day."
    ]

    upper = facts.get("total_upper_80")
    if upper:
        parts.append(
            f"To be safe on stock, plan for {number(upper, 1)} rather than the middle "
            "estimate; that is the top of the likely range."
        )

    peak = facts.get("peak_day")
    if peak:
        parts.append(
            f"The busiest single day looks like {peak['date']}, at around "
            f"{number(peak['units'], 1)} units."
        )

    kept = facts.get("covariates_kept") or []
    rejected = facts.get("covariates_rejected") or []
    if kept:
        parts.append(
            f"It tested outside signals against this product's own history and kept "
            f"{_join(kept)}" + (f", dropping {_join(rejected)}." if rejected else ".")
        )
    elif rejected:
        parts.append(
            f"It tested {_join(rejected)} against this product's own history and kept "
            "none of them — the sales pattern alone predicted it better."
        )

    accuracy = facts.get("accuracy")
    if accuracy and accuracy.get("improvement_over_naive_pct") is not None:
        parts.append(
            f"Checked against the last {accuracy['windows']} stretches of real history it "
            f"had never seen, it was {number(accuracy['improvement_over_naive_pct'], 1)}% "
            "more accurate than simply repeating last week."
        )
    elif facts.get("accuracy_note"):
        parts.append(facts["accuracy_note"])

    return " ".join(parts)


def _render_accuracy(facts: dict, entities: Entities) -> str:
    accuracy = facts.get("accuracy")
    product = facts.get("product", "this product")
    if not accuracy:
        return (
            f"There is no accuracy figure for **{product}**. "
            + facts.get("accuracy_note", "")
        ).strip()

    parts = []
    improvement = accuracy.get("improvement_over_naive_pct")
    if improvement is not None:
        parts.append(
            f"On **{product}**, the forecast was tested against "
            f"{accuracy['windows']} separate periods of real history it had not seen, "
            f"and beat simply repeating last week by {number(improvement, 1)}%."
        )
    else:
        parts.append(
            f"On **{product}**, the forecast was tested against "
            f"{accuracy['windows']} periods of held-out history."
        )

    # MASE and the improvement figure are the same idea measured two ways -- one
    # scales by the in-sample naive error, the other races the model against a
    # seasonal-naive forecaster on the same held-out windows -- so they can point
    # opposite ways on a spiky series. Reporting both as plain comparisons reads
    # as a contradiction. The race is the honest headline; the scaled score is
    # only worth a sentence when it contradicts, and then it is a caution.
    mase = accuracy.get("mase")
    if mase is not None and mase >= 1 and improvement is not None and improvement > 0:
        parts.append(
            "One caution: measured against this product's own day-to-day swings "
            "rather than against the other methods, it is no more accurate than a "
            "simple repeat. Demand here is spiky enough that no method has much "
            "of an edge."
        )
    elif mase is not None and mase >= 1:
        parts.append(
            "Measured against this product's own day-to-day swings, it is no more "
            "accurate than simply repeating the same week — treat the numbers as a "
            "rough guide, not a plan."
        )

    coverage = accuracy.get("coverage_80")
    if coverage is not None:
        parts.append(
            f"The likely range held up too: {number(coverage * 100)}% of real days "
            "landed inside it, against the 80% it promises."
        )

    baselines = accuracy.get("baselines") or []
    scored = [row for row in baselines if row.get("mase") is not None]
    if len(scored) > 1:
        best = scored[0]
        chosen = accuracy.get("best_model")
        parts.append(
            f"{len(scored)} different methods were run over the identical periods so "
            f"they could be compared fairly, and {best['model']} came out in front"
            + (" — that is the one used here." if best["model"] == chosen
               else f", ahead of the {chosen} used here.")
        )

    return " ".join(parts)


def _render_sales(facts: dict, entities: Entities) -> str:
    if facts.get("product"):
        return _render_sales_one(facts)
    return _render_sales_many(facts)


def _render_sales_one(facts: dict) -> str:
    product = facts["product"]
    window = facts.get("window_days", 30)
    parts = [
        f"{_assumed_product(facts)}**{product}** sold "
        f"**{number(facts.get('units_recent_window'), 1)} units** in the last "
        f"{window} days, about {number(facts.get('mean_units_per_day_recent'), 1)} a day."
    ]

    change = facts.get("change_vs_prior_pct")
    if change is not None:
        direction = "up" if change >= 0 else "down"
        parts.append(
            f"That is {direction} {signed_pct(abs(change))} on the "
            f"{window} days before it ({number(facts.get('units_prior_window'), 1)} units)."
        )

    best = facts.get("best_day")
    if best:
        parts.append(
            f"Its best single day on record was {best['date']}, at "
            f"{number(best['units'], 1)} units."
        )

    weekend = facts.get("weekend_effect_pct")
    if weekend is not None:
        direction = "higher" if weekend >= 0 else "lower"
        parts.append(
            f"Measured on its own history, weekend demand runs "
            f"{number(abs(weekend), 1)}% {direction} than weekdays."
        )

    zeros = facts.get("zero_days_in_window")
    if zeros:
        parts.append(f"{zeros} of those {window} days had no sales at all.")

    return " ".join(parts)


def _render_sales_many(facts: dict) -> str:
    window = facts.get("window_days", 30)
    parts = [
        f"Across {facts.get('products_compared', 0)} products, the last {window} days "
        f"brought **{number(facts.get('total_units_recent'), 1)} units**."
    ]

    overall = facts.get("overall_change_pct")
    if overall is not None:
        direction = "up" if overall >= 0 else "down"
        parts.append(
            f"That is {direction} {number(abs(overall), 1)}% on the {window} days before."
        )

    falling = facts.get("falling_fastest") or []
    if falling and falling[0].get("change_pct") is not None:
        worst = falling[0]
        parts.append(
            f"Falling fastest is **{worst['product']}**, down "
            f"{number(abs(worst['change_pct']), 1)}% to "
            f"{number(worst['units_recent'], 1)} units."
        )

    rising = facts.get("rising_fastest") or []
    if rising and rising[0].get("change_pct") is not None and rising[0]["change_pct"] > 0:
        best = rising[0]
        parts.append(
            f"Rising fastest is **{best['product']}**, up "
            f"{number(best['change_pct'], 1)}% to {number(best['units_recent'], 1)} units."
        )

    volume = facts.get("top_by_volume") or []
    if volume:
        parts.append(
            f"By sheer volume the leader is {volume[0]['product']} at "
            f"{number(volume[0]['units_recent'], 1)} units."
        )

    return " ".join(parts)


def _render_social(facts: dict, entities: Entities) -> str:
    product = facts.get("product", "this product")
    documents = facts.get("documents_analysed", 0)
    label = facts.get("overall_label", "mixed")
    provenance = {
        "live": "harvested just now",
        "cache": "from a recent harvest, reused rather than re-scraped",
        "fixture": "replayed from a recording — real posts, but not current",
        "none": "nothing was retrieved",
    }.get(facts.get("provenance", ""), facts.get("provenance", ""))

    parts = [
        f"{_assumed_product(facts)}Public opinion about **{product}** is **{label}**, "
        f"based on {number(documents)} posts from the last "
        f"{facts.get('lookback_days', 30)} days ({provenance})."
    ]

    by_platform = facts.get("by_platform") or []
    if by_platform:
        top = by_platform[0]
        share = round(100 * top["documents"] / documents) if documents else 0
        parts.append(
            f"Most of it is on {top['platform']} — {top['documents']} of the "
            f"{number(documents)} posts, {share}% of everything found."
        )

    rejected = facts.get("documents_rejected_as_noise")
    if rejected:
        parts.append(
            f"Another {number(rejected)} were harvested and thrown out as "
            "promotional or off-topic."
        )

    terms = facts.get("talking_points") or []
    if terms:
        parts.append(
            "The words people keep using are "
            + ", ".join(f"“{t['term']}” ({t['mentions']})" for t in terms[:3])
            + "."
        )

    attention = facts.get("attention_not_approval") or []
    if attention:
        signal = attention[0]
        change = signal.get("change_vs_earlier_pct")
        if change is not None and abs(change) >= 10:
            direction = "more" if change > 0 else "fewer"
            parts.append(
                f"Searches are running {number(abs(change), 1)}% {direction} than "
                "earlier in the window — that is curiosity, not approval."
            )

    failed = facts.get("sources_that_failed") or []
    if failed:
        parts.append(
            f"{len(failed)} source(s) could not be reached, so their silence is not "
            "evidence of silence."
        )

    if documents < 20:
        parts.append(
            f"With only {number(documents)} posts this is a hint about direction, "
            "not a measurement."
        )

    return " ".join(parts)


def _render_catalogue(facts: dict, entities: Entities) -> str:
    parts = []
    count = facts.get("dataset_count", 0)
    connected = facts.get("connected") or []
    if connected:
        live = connected[0]
        parts.append(
            f"You have **{count} datasets**, including a live connection with "
            f"{number(live['rows'])} rows across {live['products']} products over "
            f"{live['span_days']} days."
        )
    else:
        parts.append(f"You have **{count} datasets** available.")

    products = facts.get("products") or []
    if products:
        names = ", ".join(p["name"] for p in products[:5])
        parts.append(
            f"In {facts.get('focus_dataset', 'the current dataset')} there are "
            f"{facts.get('product_count', len(products))} products — the biggest by "
            f"volume are {names}."
        )

    forecastable = facts.get("forecastable_count")
    insufficient = facts.get("insufficient_products") or []
    if insufficient:
        parts.append(
            f"{forecastable} of them have enough history to forecast; "
            f"{len(insufficient)} do not and will be refused rather than padded."
        )
    elif forecastable:
        parts.append(f"All {forecastable} have enough history to forecast.")

    return " ".join(parts)


def _render_capability(facts: dict, entities: Entities) -> str:
    return (
        "I can answer four kinds of question about your own data. **Forecasts** — "
        "“how many kurtis will I sell next month?” — run the real model and "
        "come with a backtest. **Sales history** — “which product is falling "
        "fastest?” — is computed from your transactions. **Social signal** — "
        "“what are people saying about the crop top?” — harvests public posts "
        "and tells you where they came from. And **what data you have** — datasets, "
        "products, and how much history each one holds. "
        "If a product has too little history to forecast honestly, I will say so "
        "rather than invent one."
    )


def _join(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    words = [str(i) for i in items]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"
