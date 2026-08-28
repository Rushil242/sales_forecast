"""Reproduce the sentiment model comparison behind the configured default.

Runs every candidate model over a small hand-labelled set of consumer product
opinions and reports per-sentence polarity plus overall agreement. This is the
evidence for choosing a social-domain model over FinBERT, which the project's
literature review cites but which was fine-tuned on financial communications.

    python -m scripts.compare_sentiment_models
"""

from __future__ import annotations

import argparse
import sys

DEFAULT_MODELS = [
    "cardiffnlp/twitter-roberta-base-sentiment-latest",
    "ProsusAI/finbert",
]

# (text, expected polarity sign); 0 means "should sit near neutral".
LABELLED: list[tuple[str, int]] = [
    ("I absolutely love this t-light holder, gorgeous quality and it arrived fast", 1),
    ("This storage bag is trending everywhere, everyone is obsessed with it", 1),
    ("Beautiful product, exactly as described, would definitely recommend", 1),
    ("Terrible quality, broke within a week. Complete waste of money", -1),
    ("Not good at all, would not recommend to anyone", -1),
    ("Arrived damaged and the refund process was a nightmare", -1),
    ("The package arrived on Tuesday as scheduled", 0),
    ("This item is sold in packs of twelve", 0),
]


def is_correct(polarity: float, expected: int) -> bool:
    if expected == 1:
        return polarity > 0.25
    if expected == -1:
        return polarity < -0.25
    return abs(polarity) < 0.5


def evaluate(model_id: str) -> float:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForSequenceClassification.from_pretrained(model_id)
    model.eval()

    labels = {str(v).lower(): k for k, v in model.config.id2label.items()}
    positive = next(v for k, v in labels.items() if k.startswith("pos"))
    negative = next(v for k, v in labels.items() if k.startswith("neg"))

    encoded = tokenizer(
        [text for text, _ in LABELLED],
        padding=True, truncation=True, max_length=256, return_tensors="pt",
    )
    with torch.no_grad():
        probabilities = torch.softmax(model(**encoded).logits, dim=-1)

    print(f"\n=== {model_id}")
    correct = 0
    for (text, expected), row in zip(LABELLED, probabilities, strict=True):
        polarity = float(row[positive]) - float(row[negative])
        ok = is_correct(polarity, expected)
        correct += ok
        print(f"  {polarity:+.3f}  expected {expected:+d}  {'ok  ' if ok else 'MISS'}  {text[:56]}")

    accuracy = correct / len(LABELLED)
    print(f"  agreement: {correct}/{len(LABELLED)} = {accuracy:.2f}")
    return accuracy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args(argv)

    results = {model_id: evaluate(model_id) for model_id in args.models}

    print("\n=== summary")
    for model_id, accuracy in sorted(results.items(), key=lambda kv: -kv[1]):
        print(f"  {accuracy:.2f}  {model_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
