"""The browse tree behind the data picker.

Why this exists
---------------
A dropdown of thirty product names is a bad way to choose what to forecast. It
hides the shape of the catalogue, it cannot express "all of menswear", and it
makes every product look equally worth forecasting when most of them are not.

This turns a dataset into something you can walk: dimensions the data actually
has (category, colour, region), the values inside each, and the products beneath
those. Every node carries its own volume and data-quality grade, so a buyer can
see before clicking whether a branch is even forecastable.

The grades are the honest part. A node marked ``insufficient`` will be refused by
the forecast endpoint, and saying so on the tile is much better than letting
someone pick it and meet an error.
"""

from __future__ import annotations

import logging

import pandas as pd

from app.config import get_settings
from app.services.ingestion import Dataset

LOG = logging.getLogger(__name__)

# Columns worth grouping by, in the order a merchandiser would think about them.
DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("category", "Category", "How the catalogue is organised"),
    ("color", "Colour", "Variant-level demand"),
    ("region", "Market", "Where it sold"),
)


def _grade(span_days: int) -> str:
    """Data-quality grade from the span of history, matching the forecast gate."""
    settings = get_settings()
    if span_days < settings.min_observations:
        return "insufficient"
    if span_days < settings.recommended_observations:
        return "limited"
    if span_days < 2 * settings.recommended_observations:
        return "adequate"
    return "good"


def _node(frame: pd.DataFrame, label: str, **extra: object) -> dict:
    span = int((frame["date"].max() - frame["date"].min()).days) + 1
    return {
        "label": label,
        "products": int(frame["product"].nunique()),
        "units": float(frame["units"].sum()),
        "observations": int(frame["date"].nunique()),
        "span_days": span,
        "first_date": frame["date"].min().strftime("%Y-%m-%d"),
        "last_date": frame["date"].max().strftime("%Y-%m-%d"),
        "data_quality": _grade(span),
        **extra,
    }


def build_taxonomy(dataset: Dataset) -> dict:
    """Every way this dataset can be sliced, with the stats to choose between them."""
    frame = dataset.frame

    dimensions: list[dict] = []
    for column, label, blurb in DIMENSIONS:
        if column not in frame.columns:
            continue
        present = frame[frame[column].notna()]
        if present.empty:
            continue

        values: list[dict] = []
        for value, group in present.groupby(present[column].astype(str)):
            # A single-product "group" is just that product wearing a hat; it adds
            # a redundant level to the browse tree rather than a useful one.
            values.append(_node(
                group, str(value),
                value=str(value),
                dimension=column,
                kind="group",
            ))

        values.sort(key=lambda v: v["units"], reverse=True)
        # A dimension where everything falls in one bucket is not a way to browse.
        if len(values) < 2:
            continue

        dimensions.append({
            "key": column,
            "label": label,
            "description": blurb,
            "values": values,
        })

    products: list[dict] = []
    for name, group in frame.groupby("product"):
        node = _node(group, str(name), value=str(name), kind="product")
        for column, _, _ in DIMENSIONS:
            if column in group.columns:
                first = group[column].dropna()
                node[column] = str(first.iloc[0]) if len(first) else None
        products.append(node)
    products.sort(key=lambda p: p["units"], reverse=True)

    everything = _node(frame, "Everything", value="", kind="all")

    return {
        "dataset": dataset.name,
        "total": everything,
        "dimensions": dimensions,
        "products": products,
    }


def describe_selection(
    dataset: Dataset, product_name: str | None, filters: dict[str, str] | None
) -> str:
    """A human label for whatever the user picked, for the forecast header."""
    if product_name:
        return product_name
    if filters:
        return " · ".join(str(v) for v in filters.values())
    return f"All products in {dataset.name}"
