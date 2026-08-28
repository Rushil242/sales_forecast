"""Sentiment scoring, including the measurement that justifies the model choice.

The labelled set below is small and hand-written. It is not a benchmark; it is a
sanity floor that catches a model whose polarity is inverted, saturated, or
domain-mismatched to the point of calling plain complaints neutral.
"""

from __future__ import annotations

import pytest

from app.services.social.base import RawDocument
from app.services.social.sentiment import (
    _score_with_lexicon,
    reset_model,
    score_documents_sync,
)

# (text, expected polarity sign) where 0 means "should be near neutral".
LABELLED = [
    ("I absolutely love this t-light holder, gorgeous quality and it arrived fast", 1),
    ("This storage bag is trending everywhere, everyone is obsessed with it", 1),
    ("Beautiful product, exactly as described, would definitely recommend", 1),
    ("Terrible quality, broke within a week. Complete waste of money", -1),
    ("Not good at all, would not recommend to anyone", -1),
    ("Arrived damaged and the refund process was a nightmare", -1),
    ("The package arrived on Tuesday as scheduled", 0),
    ("This item is sold in packs of twelve", 0),
]


def _polarities(texts: list[str]) -> list[float]:
    documents = [RawDocument(source="test", title=text) for text in texts]
    score_documents_sync(documents)
    return [d.sentiment_score for d in documents]


def test_lexicon_fallback_gets_the_sign_right():
    """The offline path must at least agree on direction for clear cases."""
    documents = [RawDocument(source="test", title=text) for text, _ in LABELLED]
    descriptor = _score_with_lexicon(documents)

    assert descriptor.kind == "lexicon"
    for document, (text, expected) in zip(documents, LABELLED, strict=True):
        if expected == 1:
            assert document.sentiment_score > 0, text
        elif expected == -1:
            assert document.sentiment_score < 0, text


def test_lexicon_handles_negation():
    documents = [
        RawDocument(source="t", title="This is good quality and I recommend it"),
        RawDocument(source="t", title="This is not good quality and I do not recommend it"),
    ]
    _score_with_lexicon(documents)
    assert documents[0].sentiment_score > 0
    assert documents[1].sentiment_score < 0


def test_scores_are_bounded():
    documents = [RawDocument(source="t", title="love " * 50)]
    _score_with_lexicon(documents)
    assert -1.0 <= documents[0].sentiment_score <= 1.0


def test_empty_input_is_handled():
    descriptor = score_documents_sync([])
    assert descriptor.name == "none"


@pytest.mark.slow
@pytest.mark.network
def test_configured_transformer_classifies_consumer_opinion():
    """The default model must handle ordinary product opinion correctly.

    Measured on this set (see scripts/compare_sentiment_models.py):

        cardiffnlp/twitter-roberta-base-sentiment-latest   8/8
        ProsusAI/finbert                                   6/8

    FinBERT misses exactly the two cases that matter most for consumer
    listening: it scores "Not good at all, would not recommend to anyone" at
    -0.00 and "everyone is obsessed with it" at -0.03, because it was fine-tuned
    on financial rather than consumer language. The 7/8 floor below is therefore
    a threshold FinBERT genuinely fails and the configured default clears.
    """
    reset_model()
    texts = [text for text, _ in LABELLED]
    polarities = _polarities(texts)

    correct = 0
    for polarity, (_text, expected) in zip(polarities, LABELLED, strict=True):
        if expected == 1:
            correct += polarity > 0.25
        elif expected == -1:
            correct += polarity < -0.25
        else:
            correct += abs(polarity) < 0.5

    accuracy = correct / len(LABELLED)
    assert accuracy >= 0.875, (
        f"Only {correct}/{len(LABELLED)} classified correctly. "
        f"Polarities: {[round(p, 3) for p in polarities]}"
    )


@pytest.mark.slow
@pytest.mark.network
def test_strong_opinions_score_further_from_zero_than_factual_statements():
    """Polarity must preserve intensity, not collapse to the argmax label."""
    reset_model()
    strong, factual = _polarities([
        "I absolutely love this, best purchase I have ever made",
        "This item is sold in packs of twelve",
    ])
    assert abs(strong) > abs(factual)
