"""Transformer sentiment scoring, plus a dependency-free lexicon fallback.

Choice of model -- and why it is not FinBERT
--------------------------------------------
The project's literature review cites FinBERT (Araci, 2019), so FinBERT was
implemented and measured first. On consumer social text it performs poorly,
because it was fine-tuned on financial communications -- earnings calls, analyst
notes, market commentary -- where "positive" means bullish, not *pleased*.
On the labelled set in ``tests/test_sentiment.py`` FinBERT scores 6/8, missing
"Not good at all, would not recommend to anyone" (polarity -0.00, labelled
neutral) and "everyone is obsessed with it" (-0.03).

The default is therefore ``cardiffnlp/twitter-roberta-base-sentiment-latest``,
a RoBERTa fine-tuned on ~124M tweets, which is the same register as the social
and news-headline text this agent actually harvests. It scores 8/8 on the same
set, rating those two sentences -0.91 and +0.65. FinBERT remains selectable via
``RETAILIQ_SENTIMENT_MODEL_ID``; ``scripts/compare_sentiment_models.py``
reproduces the comparison.

Scoring
-------
Polarity is ``P(positive) - P(negative)``, not the argmax label. The probability
difference preserves intensity: a post the model is 95% sure is positive should
move the index further than one it is 55% sure about, and a confidently-neutral
post should move it barely at all.

If transformers or the model weights are unavailable, a small lexicon scorer
takes over so the pipeline still returns something. The response always reports
which of the two actually ran -- they are not equivalent, and the UI says so.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.services.social.base import RawDocument

LOG = logging.getLogger(__name__)

_model: Any = None
_tokenizer: Any = None
_load_failed = False
_lock = threading.Lock()

# Compact opinion lexicon for the fallback path. Deliberately small: it exists to
# keep the service alive, not to compete with a transformer.
POSITIVE_WORDS = frozenset("""
love loved lovely great excellent amazing awesome perfect best fantastic
wonderful beautiful happy pleased recommend recommended quality durable
gorgeous stunning brilliant favourite favorite worth bargain delighted
impressed sturdy charming adorable pretty nice good popular trending
selling bestseller must-have obsessed
""".split())

NEGATIVE_WORDS = frozenset("""
hate hated awful terrible horrible worst bad poor disappointing disappointed
broken cheap flimsy useless waste refund returned damaged defective overpriced
rubbish faulty complaint problem issue avoid regret unhappy annoying
delayed missing wrong scam fake
""".split())

NEGATORS = frozenset({
    "not", "no", "never", "isnt", "isn't", "wasnt", "wasn't",
    "dont", "don't", "didnt", "didn't", "cant", "can't", "without",
})


@dataclass
class SentimentModelDescriptor:
    name: str
    kind: str  # transformer | lexicon
    detail: str
    device: str | None = None


def _load_transformer():
    """Load and memoise the configured sentiment model.

    Returns ``(tokenizer, model)``, or ``None`` if it could not be loaded.
    """
    global _model, _tokenizer, _load_failed

    if _model is not None:
        return _tokenizer, _model
    if _load_failed:
        return None

    with _lock:
        if _model is not None:
            return _tokenizer, _model
        if _load_failed:
            return None

        settings = get_settings()
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            LOG.info("Loading sentiment model %s (first run downloads ~440 MB)",
                     settings.sentiment_model_id)
            _tokenizer = AutoTokenizer.from_pretrained(settings.sentiment_model_id)
            _model = AutoModelForSequenceClassification.from_pretrained(
                settings.sentiment_model_id
            )
            _model.eval()

            device = settings.resolve_device()
            if device != "cpu":
                try:
                    _model.to(device)
                except Exception as exc:
                    LOG.warning("Could not move sentiment model to %s (%s); staying on CPU",
                                device, exc)
            torch.set_grad_enabled(False)
            LOG.info("Sentiment model ready: %s", settings.sentiment_model_id)
            return _tokenizer, _model
        except Exception as exc:
            _load_failed = True
            LOG.warning(
                "Sentiment model %s unavailable (%s); falling back to lexicon scorer",
                settings.sentiment_model_id, exc,
            )
            return None


def reset_model() -> None:
    """Clear the memoised model (used by tests)."""
    global _model, _tokenizer, _load_failed
    with _lock:
        _model = None
        _tokenizer = None
        _load_failed = False


def _label_index(model) -> dict[str, int]:
    """Resolve label positions from the model config.

    Checkpoints disagree on label ordering -- FinBERT and the Cardiff RoBERTa put
    positive and negative at different indices -- so reading id2label is the only
    safe approach. Handles both descriptive names and bare LABEL_0/1/2 forms.
    """
    id2label = {int(k): str(v).lower() for k, v in model.config.id2label.items()}
    resolved: dict[str, int] = {}
    for index, label in id2label.items():
        if label.startswith("pos"):
            resolved["positive"] = index
        elif label.startswith("neg"):
            resolved["negative"] = index
        elif label.startswith("neu"):
            resolved["neutral"] = index

    if "positive" not in resolved or "negative" not in resolved:
        # Bare LABEL_0/LABEL_1/LABEL_2 checkpoints. Both FinBERT-style and
        # Cardiff-style three-class heads order as negative/neutral/positive.
        raise ValueError(
            f"Cannot resolve sentiment labels from id2label={id2label}. "
            "Set RETAILIQ_SENTIMENT_MODEL_ID to a model with named labels."
        )
    return resolved


def _score_with_transformer(documents: list[RawDocument]) -> SentimentModelDescriptor | None:
    loaded = _load_transformer()
    if loaded is None:
        return None
    tokenizer, model = loaded

    import torch

    settings = get_settings()
    labels = _label_index(model)
    device = next(model.parameters()).device

    texts = [document.content for document in documents]
    for start in range(0, len(texts), settings.sentiment_batch_size):
        batch = texts[start:start + settings.sentiment_batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=settings.sentiment_max_length,
            return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            probabilities = torch.softmax(model(**encoded).logits, dim=-1).cpu()

        for offset, row in enumerate(probabilities):
            positive = float(row[labels["positive"]])
            negative = float(row[labels["negative"]])
            neutral = float(row[labels.get("neutral", 0)])

            document = documents[start + offset]
            # Signed polarity preserving intensity, not just the argmax label.
            document.sentiment_score = round(positive - negative, 4)
            document.confidence = round(float(row.max()), 4)
            document.sentiment_label = max(
                (("positive", positive), ("negative", negative), ("neutral", neutral)),
                key=lambda pair: pair[1],
            )[0]

    return SentimentModelDescriptor(
        name=settings.sentiment_model_id,
        kind="transformer",
        detail="three-class sentiment head; polarity = P(positive) - P(negative)",
        device=str(device),
    )


def _score_with_lexicon(documents: list[RawDocument]) -> SentimentModelDescriptor:
    for document in documents:
        tokens = re.findall(r"[a-z']+", document.content.lower())
        score = 0.0
        for index, token in enumerate(tokens):
            weight = 0.0
            if token in POSITIVE_WORDS:
                weight = 1.0
            elif token in NEGATIVE_WORDS:
                weight = -1.0
            if weight and index > 0 and tokens[index - 1] in NEGATORS:
                weight = -weight
            score += weight

        hits = sum(1 for token in tokens if token in POSITIVE_WORDS or token in NEGATIVE_WORDS)
        polarity = score / hits if hits else 0.0
        document.sentiment_score = round(max(-1.0, min(1.0, polarity)), 4)
        # A lexicon has no calibrated probability; confidence scales with evidence.
        document.confidence = round(min(1.0, hits / 5), 4)
        document.sentiment_label = (
            "positive" if document.sentiment_score > 0.15
            else "negative" if document.sentiment_score < -0.15
            else "neutral"
        )

    return SentimentModelDescriptor(
        name="builtin-lexicon",
        kind="lexicon",
        detail="Fallback keyword scorer with negation handling. Far less accurate "
               "than FinBERT; results are indicative only.",
    )


def score_documents_sync(documents: list[RawDocument]) -> SentimentModelDescriptor:
    """Score in place, preferring the transformer and falling back to the lexicon."""
    if not documents:
        return SentimentModelDescriptor(
            name="none", kind="lexicon", detail="No documents to score."
        )
    try:
        scored = _score_with_transformer(documents)
    except Exception as exc:
        LOG.warning("Transformer scoring failed (%s); using lexicon", exc)
        scored = None
    return scored or _score_with_lexicon(documents)


async def score_documents(documents: list[RawDocument]) -> SentimentModelDescriptor:
    """Async wrapper. Transformer inference is CPU-bound, so it runs off the loop."""
    return await asyncio.to_thread(score_documents_sync, documents)
