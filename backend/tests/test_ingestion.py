"""Ingestion and schema-resolution tests."""

from __future__ import annotations

import pandas as pd
import pytest

from app.core.errors import InvalidCSVError, SchemaError
from app.services.ingestion import build_dataset, load_csv, resolve_columns


def test_resolves_canonical_column_names():
    resolved = resolve_columns(
        ["Transaction ID", "Date", "Product Name", "Units Sold", "Unit Price", "Region"]
    )
    assert resolved["date"] == "Date"
    assert resolved["product"] == "Product Name"
    assert resolved["units"] == "Units Sold"


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (["order_date", "sku", "qty"], ("order_date", "sku", "qty")),
        (["InvoiceDate", "Description", "Quantity"], ("InvoiceDate", "Description", "Quantity")),
        (["DATE", "PRODUCT", "UNITS"], ("DATE", "PRODUCT", "UNITS")),
        (["ds", "item name", "y"], ("ds", "item name", "y")),
    ],
)
def test_accepts_alternative_schemas(headers, expected):
    """The old implementation demanded ten exact column names; this one does not."""
    resolved = resolve_columns(headers)
    assert (resolved["date"], resolved["product"], resolved["units"]) == expected


def test_rejects_missing_required_columns():
    frame = pd.DataFrame({"Date": ["2024-01-01"], "Revenue": [10.0]})
    with pytest.raises(SchemaError) as excinfo:
        build_dataset(frame, "bad.csv")
    assert set(excinfo.value.details["missing_fields"]) == {"product", "units"}


def test_optional_columns_are_optional(transactions):
    """Payment Method is absent from real-world data and must not be required."""
    frame = transactions.drop(columns=["Product Category", "Region", "Unit Price"])
    dataset = build_dataset(frame, "minimal.csv")
    assert "region" not in dataset.frame.columns
    assert len(dataset.frame) == len(frame)


def test_drops_unparsable_rows_and_reports_it(transactions):
    frame = transactions.copy()
    # A real CSV carries everything as text, so widen the dtype before injecting
    # the unparsable values pandas would otherwise refuse to store.
    frame["Units Sold"] = frame["Units Sold"].astype(object)
    frame.loc[0, "Date"] = "not-a-date"
    frame.loc[1, "Units Sold"] = "abc"
    dataset = build_dataset(frame, "messy.csv")

    assert len(dataset.frame) == len(frame) - 2
    assert any("unparsable" in warning for warning in dataset.warnings)


def test_negative_quantities_excluded_as_returns(transactions):
    frame = transactions.copy()
    frame.loc[0, "Units Sold"] = -5
    dataset = build_dataset(frame, "returns.csv")

    assert (dataset.frame["units"] >= 0).all()
    assert any("returns" in warning for warning in dataset.warnings)


def test_parses_non_utf8_encoding(transactions):
    content = transactions.to_csv(index=False).encode("latin-1")
    dataset = load_csv(content, "latin.csv")
    assert len(dataset.frame) == len(transactions)


def test_rejects_empty_upload():
    with pytest.raises(InvalidCSVError):
        load_csv(b"", "empty.csv")


def test_fingerprint_is_content_addressed(transactions):
    first = build_dataset(transactions, "a.csv")
    second = build_dataset(transactions, "b.csv")
    assert first.fingerprint() == second.fingerprint()

    altered = transactions.copy()
    altered.loc[0, "Units Sold"] = 9999
    assert build_dataset(altered, "a.csv").fingerprint() != first.fingerprint()
