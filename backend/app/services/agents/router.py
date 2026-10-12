"""Deciding which sub-agent answers, without asking a model to decide.

Why this is rule-based
----------------------
The textbook agent routes with an LLM call. Here that would be the wrong trade
three times over. It doubles the latency of every turn for a decision that
keyword evidence settles correctly; it doubles the cost in a project whose
Gemini free tier is **20 requests per day**, so an LLM router alone would exhaust
the quota in ten questions; and it makes the assistant stop working entirely on
the day the quota runs out, which -- in a demo -- is the day it matters.

So intent is scored from explicit lexical evidence, and the score is reported.
When the evidence genuinely is ambiguous *and* an LLM call is affordable, the
tie can be escalated (``escalate=True``); the deterministic answer stands
otherwise. The router is therefore an optimisation that degrades to correct
rather than a dependency that degrades to broken.
"""

from __future__ import annotations

import logging
import re

from app.services.agents.entities import resolve
from app.services.agents.schemas import Entities, RouteDecision

LOG = logging.getLogger(__name__)

# Phrases are weighted: a phrase that can only mean one thing outscores a word
# that merely leans. "what are people saying" is unambiguous; "trend" is not,
# because a sales trend and a social trend are different questions.
SIGNALS: dict[str, list[tuple[str, float]]] = {
    "forecast": [
        (r"\bforecast(?:ing|s|ed)?\b", 3.0),
        (r"\bpredict(?:ion|ions|ed)?\b", 3.0),
        (r"\bhow many .* (?:will|shall|am i going to)\b", 3.5),
        (r"\b(?:next|coming|upcoming|following)\s+(?:\d+\s+)?(?:day|week|month|quarter)", 2.5),
        (r"\bexpect(?:ed|ing)?\b", 1.5),
        (r"\bhow much (?:stock|inventory) (?:should|do) i\b", 3.0),
        (r"\b(?:should i|how much should i) (?:order|reorder|buy|stock)\b", 3.0),
        (r"\bdemand\b", 1.2),
        (r"\bprojection\b", 2.0),
        (r"\bgoing forward\b", 1.5),
    ],
    "sales_history": [
        (r"\bhow (?:did|has|have)\b", 2.5),
        (r"\b(?:last|past|previous|recent)\s+(?:\d+\s+)?(?:day|week|month|quarter|year)", 2.0),
        (r"\bsold\b", 2.0),
        (r"\bbest[- ]?sell(?:er|ing)\b", 3.0),
        (r"\bworst[- ]?(?:sell(?:er|ing)|perform)", 3.0),
        (r"\btop\s+\d*\s*products?\b", 3.0),
        (r"\b(?:falling|dropping|declining|rising|growing)\s+(?:fastest|most|quickest)\b", 3.5),
        (r"\bcompare(?:d)?\b", 2.0),
        (r"\brevenue\b", 1.5),
        (r"\bhistory\b", 2.0),
        (r"\bso far\b", 1.5),
        (r"\bweekend\b", 1.5),
        (r"\bwhich (?:product|item|sku)s? (?:is|are|sell)", 2.5),
    ],
    "social": [
        (r"\b(?:what|how) are people (?:saying|talking|feeling)\b", 4.0),
        (r"\bsentiment\b", 3.5),
        (r"\bsocial (?:media|signal|buzz)\b", 3.5),
        (r"\b(?:instagram|reddit|pinterest|youtube|twitter|x\.com)\b", 3.0),
        (r"\bviral\b", 3.0),
        (r"\bbuzz\b", 2.5),
        (r"\bhype\b", 2.5),
        (r"\bonline (?:chatter|discussion|talk)\b", 3.0),
        (r"\bpublic opinion\b", 3.5),
        (r"\bpeople (?:like|love|hate)\b", 2.5),
        (r"\btrending (?:on|in)\b", 3.0),
        (r"\breviews?\b", 2.0),
        (r"\bmentions?\b", 2.0),
    ],
    "accuracy": [
        (r"\bhow accurate\b", 4.0),
        (r"\baccuracy\b", 3.0),
        (r"\b(?:can|should) i trust\b", 3.5),
        (r"\bhow (?:good|reliable|confident)\b", 2.5),
        (r"\bbacktest(?:ing|ed)?\b", 3.5),
        (r"\bmase|rmse|smape\b", 3.5),
        (r"\bmargin of error\b", 3.0),
        (r"\bwhich model\b", 2.5),
        (r"\bhow does it compare to\b", 2.0),
    ],
    "catalogue": [
        (r"\bwhat (?:products?|items?|skus?|data)\b", 3.0),
        (r"\b(?:list|show me) (?:my |the |all )?(?:products?|items?|datasets?|data)\b", 3.5),
        (r"\bwhat (?:datasets?|data sources?)\b", 3.5),
        (r"\bhow (?:much|many) (?:data|history|records?)\b", 2.5),
        (r"\bwhat(?:'s| is) (?:connected|synced|available)\b", 3.0),
        (r"\bconnect(?:ed|ion)s?\b", 2.0),
        (r"\bshopify|zoho\b", 2.0),
        (r"\bcatalogue|catalog\b", 2.5),
    ],
    "capability": [
        (r"\bwhat can you (?:do|help)\b", 4.0),
        (r"\bwho are you\b", 4.0),
        (r"\bhelp\b", 1.5),
        (r"\bhow (?:do|does) (?:this|you|it) work\b", 3.0),
        (r"^\s*(?:hi|hey|hello|yo)\b", 3.0),
        (r"\bwhat are your (?:capabilities|features)\b", 4.0),
    ],
}

COMPILED: dict[str, list[tuple[re.Pattern[str], float]]] = {
    intent: [(re.compile(pattern, re.IGNORECASE), weight) for pattern, weight in signals]
    for intent, signals in SIGNALS.items()
}

# Below this the deterministic evidence is too thin to act on confidently.
AMBIGUOUS_BELOW = 2.5
# The gap that makes a win decisive rather than a coin toss.
DECISIVE_MARGIN = 1.5


def score_intents(message: str) -> dict[str, float]:
    """Lexical evidence for each intent. Every match contributes its weight."""
    scores: dict[str, float] = {}
    for intent, patterns in COMPILED.items():
        total = 0.0
        for pattern, weight in patterns:
            if pattern.search(message):
                total += weight
        if total:
            scores[intent] = round(total, 2)
    return scores


def _matched_phrases(message: str, intent: str, limit: int = 3) -> list[str]:
    """The literal text that triggered this intent, for the audit trail."""
    found: list[str] = []
    for pattern, _ in COMPILED.get(intent, []):
        match = pattern.search(message)
        if match:
            found.append(match.group(0).strip())
        if len(found) >= limit:
            break
    return found


def route(
    message: str,
    products: list[str],
    *,
    carried: Entities | None = None,
) -> RouteDecision:
    """Classify one message and pull its entities out.

    The returned ``confidence`` is normalised to 0-1 for display but derives from
    the raw margin: an intent that wins by a wide margin over a strong runner-up
    is more certain than one that wins by 0.2.
    """
    entities = resolve(message, products, carried=carried)
    scores = score_intents(message)

    if not scores:
        # No lexical evidence at all. A named product still tells us something:
        # someone typing just a product name almost always wants its outlook.
        if entities.product and entities.product_confidence >= 0.9:
            return RouteDecision(
                intent="forecast",
                confidence=0.4,
                reason=(
                    f"No question words matched, but '{entities.product}' is a product "
                    "in the data, so this was read as a demand question."
                ),
                entities=entities,
            )
        return RouteDecision(
            intent="capability",
            confidence=0.3,
            reason="Nothing in the message matched a known kind of question.",
            entities=entities,
        )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_intent, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = top_score - runner_up

    # A forecast question about a product is still a forecast question even when
    # it mentions last month's sales as context; but "how did X do last month"
    # with no forward-looking words is history. The margin captures this without
    # a special case, so only genuinely tied scores need one.
    confidence = min(0.99, 0.45 + 0.12 * top_score + 0.15 * margin)
    phrases = _matched_phrases(message, top_intent)
    reason = (
        f"Matched {', '.join(repr(p) for p in phrases)} for {top_intent}"
        if phrases else f"Scored highest for {top_intent}"
    )
    if runner_up:
        reason += f" (score {top_score} against {ranked[1][0]} at {runner_up})"

    return RouteDecision(
        intent=top_intent,  # type: ignore[arg-type]
        confidence=round(confidence, 3),
        reason=reason,
        entities=entities,
    )


def is_ambiguous(decision: RouteDecision, message: str) -> bool:
    """Whether an LLM tie-break would actually be worth a request."""
    scores = score_intents(message)
    if not scores:
        return True
    ranked = sorted(scores.values(), reverse=True)
    top = ranked[0]
    margin = top - (ranked[1] if len(ranked) > 1 else 0.0)
    return top < AMBIGUOUS_BELOW or margin < DECISIVE_MARGIN
