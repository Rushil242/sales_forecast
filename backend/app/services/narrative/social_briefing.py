"""The owner-facing brief for the social page.

Same shape and same discipline as the forecast brief: prefer Gemini, run its output
through the number-provenance guard, and fall back to a deterministic template that
cannot invent anything.

One rule is specific to this page. **Search interest is not sentiment.** Google
Trends measures attention, not approval, so it is passed to the model in a separate
block with that stated, and the template never averages it into a mood. Getting this
wrong produces the confident nonsense of "sentiment rose 40%" when what actually
happened is that a news story made people curious.
"""

from __future__ import annotations

import logging

from app.schemas.social import SocialResponse
from app.services.narrative import client
from app.services.narrative.schemas import (
    Action,
    Finding,
    SocialBrief,
    SocialBriefEnvelope,
)

LOG = logging.getLogger(__name__)

# Platforms that report attention rather than opinion, and must stay out of any
# sentence about how people feel.
SIGNAL_PLATFORMS = {"Google Trends"}

PROVENANCE_NOTE = {
    "live": "harvested just now",
    "cache": "from a recent harvest, reused rather than re-scraped",
    "fixture": "replayed from a recorded harvest -- real documents, but not current",
    "none": "no documents were retrieved",
}


def build_payload(response: SocialResponse) -> dict:
    """Everything the model may reason from, and nothing it may not."""
    opinion = [p for p in response.platforms if p.platform not in SIGNAL_PLATFORMS]
    signal = [p for p in response.platforms if p.platform in SIGNAL_PLATFORMS]

    working = [c for c in response.connectors if c.status == "ok"]
    failed = [c for c in response.connectors if c.status not in ("ok", "empty")]

    active = [p for p in response.timeline if p.document_count]
    busiest_day = max(active, key=lambda p: p.document_count) if active else None

    return {
        "product": response.query,
        "lookback_days": response.lookback_days,
        "provenance": response.provenance,
        "evidence": {
            "documents_analysed": response.total_documents,
            "documents_rejected_as_noise": response.filtered_documents,
            "sources_returning_data": len(working),
            "sources_tried": len(response.connectors),
            "sources_that_failed": [
                {"name": c.name, "reason": c.detail[:160]} for c in failed
            ],
        },
        "mood": {
            "overall_score_minus1_to_1": round(response.overall_sentiment, 3),
            "overall_label": response.overall_label,
            "by_platform": [
                {
                    "platform": p.platform,
                    "documents": p.documents,
                    "sentiment": p.sentiment_score,
                    "positive_share": p.positive_share,
                    "negative_share": p.negative_share,
                    "change_vs_earlier_in_window_pct": p.trend_pct,
                }
                for p in opinion
            ],
        },
        # Kept apart on purpose. See the module docstring.
        "attention_not_approval": [
            {
                "platform": p.platform,
                "readings": p.documents,
                "mean_interest_0_to_100": p.engagement_rate,
                # Second half of the window against the first. This is the one
                # figure that answers "is this rising?", which is what an owner
                # actually wants to know.
                "change_vs_earlier_in_window_pct": p.trend_pct,
                "note": p.note,
            }
            for p in signal
        ],
        "talking_points": [
            {
                "term": t.term,
                "mentions": t.count,
                "sentiment": t.sentiment_score,
                "sentiment_label": t.sentiment_label,
            }
            for t in response.trending_terms[:10]
        ],
        # When the talk happened, so a finding can name a date rather than saying
        # "recently". Only days that actually carry documents are listed.
        "activity": {
            "busiest_day": (
                {"date": busiest_day.date, "documents": busiest_day.document_count}
                if busiest_day is not None else None
            ),
            "days_with_any_talk": sum(
                1 for point in response.timeline if point.document_count
            ),
            "days_observed": len(response.timeline),
        },
        # What was actually said. Titles only -- enough for the model to name a
        # concrete post, not enough for it to invent statistics about one.
        # The text, not just the title. This is the only place the model can learn
        # *why* something is being talked about -- a launch, a festival, somebody
        # well-known wearing it. It may only report a reason the posts state.
        "example_posts": [
            {
                "platform": doc.source,
                "title": doc.title[:180],
                "text": (doc.text or "")[:400],
                "mood": doc.sentiment_label,
            }
            for doc in response.top_documents[:10]
        ],
        "sentiment_model": response.sentiment_model.name,
        "warnings": response.warnings,
    }


def build_template_brief(payload: dict) -> SocialBrief:
    """Composed from measured figures alone. Cannot hallucinate."""
    product = payload["product"]
    evidence = payload["evidence"]
    mood = payload["mood"]
    days = payload["lookback_days"]

    documents = evidence["documents_analysed"]
    working = evidence["sources_returning_data"]
    tried = evidence["sources_tried"]

    if documents == 0:
        return SocialBrief(
            headline=f"Nothing public was found about {product} in the last {days} days.",
            summary=(
                f"{working} of {tried} sources returned anything. That usually means the "
                "product name is too specific to appear in public discussion, not that "
                "opinion is neutral."
            ),
            findings=[Finding(
                text="With no social signal, the demand forecast rests on sales history "
                     "alone -- which is a complete basis on its own.",
                severity="info",
            )],
            actions=[Action(
                text="Try a broader term, such as the product category or your brand "
                     "name, to see whether the category is being discussed.",
                urgency="info",
            )],
            evidence_note=f"No documents. {working} of {tried} sources responded.",
        )

    score = mood["overall_score_minus1_to_1"]
    label = mood["overall_label"]

    # "only mildly neutral" is not English. A neutral reading is not a weak version
    # of an opinion, it is the absence of one, so it gets its own phrasing.
    if label == "neutral":
        verdict = "is mixed, with no clear lean either way"
    else:
        strength = "strongly" if abs(score) > 0.5 else "broadly"
        verdict = f"is {strength} {label}"

    headline = (
        f"Public opinion about {product} {verdict}, "
        f"based on {documents} posts and articles from the last {days} days."
    )

    platforms = sorted(
        mood["by_platform"], key=lambda p: p["documents"], reverse=True
    )
    busiest = platforms[0] if platforms else None
    summary_parts = [
        f"{working} of {tried} sources returned data "
        f"({PROVENANCE_NOTE.get(payload['provenance'], payload['provenance'])})."
    ]
    if busiest:
        summary_parts.append(
            f"Most of it came from {busiest['platform']} ({busiest['documents']} items)."
        )
    if evidence["documents_rejected_as_noise"]:
        summary_parts.append(
            f"{evidence['documents_rejected_as_noise']} more were harvested and rejected "
            "as promotional or off-topic."
        )
    summary = " ".join(summary_parts)

    findings: list[Finding] = []
    product = payload["product"]

    # Rising or falling comes first. It is the only forward-looking thing on the
    # page and the one an owner can act on before their competitors do.
    for signal in payload["attention_not_approval"]:
        if not signal["readings"]:
            continue
        change = signal.get("change_vs_earlier_in_window_pct")
        interest = signal["mean_interest_0_to_100"]
        if change is not None and abs(change) >= 10:
            direction = "more" if change > 0 else "fewer"
            findings.append(Finding(
                text=(
                    f"People are searching for {product} {abs(round(change))}% "
                    f"{direction} in the second half of this month than the first. "
                    + (
                        "Interest is building, and search usually moves before "
                        "sales do."
                        if change > 0 else
                        "Interest is cooling off, so do not read past sales as a "
                        "guide to the next few weeks."
                    )
                ),
                severity="watch" if change < 0 else "info",
            ))
        elif change is not None:
            findings.append(Finding(
                text=(
                    f"Search interest in {product} is sitting at {round(interest)} "
                    "out of 100 and holding steady -- no surge, no collapse. This is "
                    "how many people are looking, not whether they liked it."
                ),
                severity="info",
            ))
        else:
            # A rise from a genuine zero has no percentage, and inventing one is
            # exactly the kind of fabricated precision this project refuses.
            findings.append(Finding(
                text=(
                    f"Search interest in {product} averages {round(interest)} out of "
                    "100. There was too little searching earlier in the window to "
                    "compare against, so we cannot say whether that is rising or "
                    "falling -- only that some people are looking."
                ),
                severity="info",
            ))

    # Where the conversation lives, phrased as somewhere to go and look.
    if busiest and documents:
        share = round(100 * busiest["documents"] / documents)
        where = (
            f"{busiest['platform']} is where this product is being talked about: "
            f"{busiest['documents']} of the {documents} posts we found are there"
        )
        if share >= 60:
            findings.append(Finding(
                text=(
                    f"{where} -- {share}% of everything. That makes this "
                    f"{busiest['platform']}'s opinion rather than the public's, so "
                    "treat it as one crowd, not the whole market."
                ),
                severity="watch",
            ))
        else:
            findings.append(Finding(
                text=f"{where}. That is the place to watch if you want to see it "
                     "for yourself.",
                severity="info",
            ))

    # The split, said the way a person would say it.
    total_docs = sum(p["documents"] for p in platforms) or 1
    pos = sum(p["positive_share"] * p["documents"] for p in platforms) / total_docs
    neg = sum(p["negative_share"] * p["documents"] for p in platforms) / total_docs
    neutral = max(0.0, 1 - pos - neg)
    if documents >= 5:
        if neutral > 0.6:
            text = (
                f"Hardly anyone is praising or complaining about {product} -- about "
                f"{round(neutral * 100)}% of the posts just mention it in passing. "
                "People are aware of it; they are not raving about it."
            )
        elif neg > 0.25:
            text = (
                f"Roughly {round(neg * 100)}% of what is said about {product} is "
                f"negative, against {round(pos * 100)}% positive. That is enough "
                "complaint to be worth reading before you reorder."
            )
        else:
            text = (
                f"About {round(pos * 100)}% of the posts about {product} are warm "
                f"and only {round(neg * 100)}% are negative. People who mention it "
                "generally like it."
            )
        findings.append(Finding(
            text=text, severity="watch" if neg > 0.25 else "info",
        ))

    # Disagreement between platforms is more actionable than the average.
    scored = [p for p in platforms if p["documents"] >= 3]
    if len(scored) >= 2:
        best = max(scored, key=lambda p: p["sentiment"])
        worst = min(scored, key=lambda p: p["sentiment"])
        if best["sentiment"] - worst["sentiment"] > 0.4:
            findings.append(Finding(
                text=(
                    f"The crowd on {best['platform']} likes this noticeably more than "
                    f"the one on {worst['platform']}. Two different audiences reaching "
                    "two different verdicts -- worth knowing which one buys from you."
                ),
                severity="watch",
            ))

    activity = payload.get("activity") or {}
    day = activity.get("busiest_day")
    if day:
        talked = activity.get("days_with_any_talk") or 0
        observed = activity.get("days_observed") or days
        if talked > observed / 2:
            findings.append(Finding(
                text=(
                    f"{product} came up on {talked} of the last {observed} days, "
                    f"busiest on {day['date']}. This is a steady drumbeat rather than "
                    "one viral moment, which is the healthier kind of attention."
                ),
                severity="info",
            ))
        else:
            findings.append(Finding(
                text=(
                    f"Talk about {product} is patchy -- {talked} of the last "
                    f"{observed} days had anything at all, and {day['documents']} of "
                    f"the posts landed on {day['date']} alone. Check what happened "
                    "that day before treating this as a trend."
                ),
                severity="watch",
            ))

    terms = payload["talking_points"][:3]
    if terms:
        leader = terms[0]
        others = ", ".join(f"\u201c{t['term']}\u201d" for t in terms[1:])
        mood_word = {
            "positive": "and the posts using it are positive",
            "negative": "and the posts using it are complaints",
        }.get(leader["sentiment_label"], "though those posts are matter-of-fact")
        findings.append(Finding(
            text=(
                f"The word that keeps coming up next to {product} is "
                f"\u201c{leader['term']}\u201d -- {leader['mentions']} times, {mood_word}. "
                + (f"After that: {others}. " if others else "")
                + "That is the language your customers are using, so it is the "
                "language your listing should use too."
            ),
            severity="info",
        ))

    if documents < 20:
        findings.append(Finding(
            text=(
                f"All of this rests on {documents} posts, which is thin. Treat it as "
                "a hint about which way the wind is blowing, not as a measurement."
            ),
            severity="watch",
        ))

    failures = evidence["sources_that_failed"]
    if failures:
        findings.append(Finding(
            text=(
                "We could not reach "
                + ", ".join(f["name"] for f in failures)
                + " this time. Silence from a source we never got to is not evidence "
                "that nobody is talking there."
            ),
            severity="info",
        ))

    actions: list[Action] = []
    if score < -0.15:
        actions.append(Action(
            text="Read the negative posts below before your next reorder -- if a "
                 "specific complaint repeats, it is a product problem, not a demand one.",
            urgency="urgent" if score < -0.4 else "watch",
        ))
    elif score > 0.15 and documents >= 20:
        actions.append(Action(
            text="Positive attention with this much volume usually leads demand. Check "
                 "stock cover before it arrives.",
            urgency="watch",
        ))
    else:
        actions.append(Action(
            text="Nothing here argues for changing your buying plan. Let the sales "
                 "history drive the decision.",
            urgency="info",
        ))

    if documents < 20:
        actions.append(Action(
            text="Re-run this on a broader term to get enough evidence to act on.",
            urgency="info",
        ))

    return SocialBrief(
        headline=headline,
        summary=summary,
        findings=findings[:6],
        actions=actions[:3],
        evidence_note=(
            f"{documents} documents from {working} of {tried} sources, "
            f"{PROVENANCE_NOTE.get(payload['provenance'], payload['provenance'])}. "
            f"Scored with {payload['sentiment_model']}."
        ),
    )


def build_brief(response: SocialResponse) -> SocialBriefEnvelope:
    """Prefer Gemini; fall back to the template, and always say which ran."""
    payload = build_payload(response)

    envelope = client.generate_social_brief(payload)
    if envelope is not None and envelope.source == "llm":
        return envelope

    warnings: list[str] = []
    flags: list[str] = []
    if envelope is not None:
        warnings, flags = envelope.warnings, envelope.guard_flags
    else:
        reason = client.unavailable_reason()
        if reason:
            warnings = [reason]

    return SocialBriefEnvelope(
        brief=build_template_brief(payload),
        source="template",
        guard_flags=flags,
        warnings=warnings,
    )
