"""CSV ingestion, schema resolution and profiling.

The previous implementation demanded ten exact column names, which meant any CSV
that was not the bundled Zara file was rejected outright. This module instead
requires only the three columns a demand forecast genuinely needs -- a date, a
product identifier and a quantity -- and resolves them through a case- and
punctuation-insensitive alias table. Everything else is an optional enrichment.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from io import BytesIO

import pandas as pd

from app.core.errors import InvalidCSVError, SchemaError

LOG = logging.getLogger(__name__)

# Canonical field -> accepted source spellings. Matching is done on a normalised
# form (lowercased, non-alphanumerics stripped), so "Units Sold", "units_sold"
# and "UNITS-SOLD" all resolve to the same field.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "orderdate", "invoicedate", "transactiondate", "day", "ds", "timestamp"),
    "product": ("productname", "product", "item", "itemname", "sku", "description",
                "productdescription", "uniqueid"),
    "units": ("unitssold", "units", "quantity", "qty", "salesquantity", "volume", "y",
              "unitsordered"),
    "unit_price": ("unitprice", "price", "sellingprice", "rate"),
    "revenue": ("totalrevenue", "revenue", "sales", "salesamount", "amount", "totalsales"),
    "region": ("region", "country", "location", "market", "store", "storelocation", "city"),
    "category": ("productcategory", "category", "department", "producttype", "segment"),
    "color": ("color", "colour", "variant"),
    "transaction_id": ("transactionid", "invoice", "invoiceno", "orderid", "id", "receipt"),
    "payment_method": ("paymentmethod", "payment", "paymenttype", "tender"),
}

REQUIRED_FIELDS = ("date", "product", "units")


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


@dataclass
class Dataset:
    """A validated transaction table plus everything we learned while loading it."""

    name: str
    frame: pd.DataFrame
    column_map: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    @property
    def has(self) -> set[str]:
        return set(self.column_map)

    def fingerprint(self) -> str:
        """Stable content hash, used to key cached runs."""
        subset = self.frame[["date", "product", "units"]]
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(subset, index=False).values.tobytes()
        )
        return digest.hexdigest()[:32]

    def products(self) -> list[str]:
        return sorted(self.frame["product"].dropna().unique().tolist())

    def regions(self) -> list[str]:
        if "region" not in self.frame:
            return []
        return sorted(self.frame["region"].dropna().astype(str).unique().tolist())


def resolve_columns(columns: list[str]) -> dict[str, str]:
    """Map canonical field names onto the actual column headers present."""
    normalised = {_normalise(col): col for col in columns}
    resolved: dict[str, str] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalised:
                resolved[field_name] = normalised[alias]
                break
    return resolved


def read_csv(content: bytes, name: str) -> pd.DataFrame:
    """Parse bytes as CSV, tolerating the encodings spreadsheets actually emit."""
    if not content:
        raise InvalidCSVError("The uploaded file is empty.")

    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            frame = pd.read_csv(BytesIO(content), encoding=encoding, skipinitialspace=True)
            if encoding != "utf-8-sig":
                LOG.info("Parsed %s using %s encoding", name, encoding)
            return frame
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.EmptyDataError as exc:
            raise InvalidCSVError("The CSV contains no parsable rows.") from exc
        except Exception as exc:  # malformed delimiters, ragged rows, ...
            raise InvalidCSVError(f"Unable to parse CSV: {exc}") from exc

    raise InvalidCSVError(
        "Could not decode the file. Save it as UTF-8 CSV and try again."
    ) from last_error


def build_dataset(frame: pd.DataFrame, name: str) -> Dataset:
    """Validate, normalise and clean a raw transaction frame."""
    if frame.empty:
        raise InvalidCSVError("The CSV contains no rows.")

    frame = frame.rename(columns=lambda c: str(c).strip())
    column_map = resolve_columns(list(frame.columns))

    missing = [f for f in REQUIRED_FIELDS if f not in column_map]
    if missing:
        raise SchemaError(
            "The dataset is missing required columns: "
            + ", ".join(missing)
            + ". A date, a product name and a units/quantity column are the minimum needed.",
            missing_fields=missing,
            found_columns=list(frame.columns),
            accepted_aliases={f: list(COLUMN_ALIASES[f]) for f in missing},
        )

    warnings: list[str] = []
    working = pd.DataFrame(index=frame.index)

    working["date"] = pd.to_datetime(
        frame[column_map["date"]], errors="coerce", format="mixed", dayfirst=False
    )
    working["product"] = frame[column_map["product"]].astype(str).str.strip()
    working["units"] = pd.to_numeric(frame[column_map["units"]], errors="coerce")

    for field_name in ("unit_price", "revenue"):
        if field_name in column_map:
            working[field_name] = pd.to_numeric(frame[column_map[field_name]], errors="coerce")
    for field_name in ("region", "category", "color", "transaction_id", "payment_method"):
        if field_name in column_map:
            working[field_name] = frame[column_map[field_name]].astype(str).str.strip()

    before = len(working)
    working = working.dropna(subset=["date", "units"])
    dropped = before - len(working)
    if dropped:
        warnings.append(
            f"Dropped {dropped:,} of {before:,} rows with an unparsable date or quantity."
        )

    negative = int((working["units"] < 0).sum())
    if negative:
        # Negative quantities are returns. They are real, but they are not demand,
        # so they are excluded from the series rather than netted off silently.
        warnings.append(
            f"Excluded {negative:,} rows with negative quantities (treated as returns, not demand)."
        )
        working = working[working["units"] >= 0]

    if working.empty:
        raise InvalidCSVError("No usable rows remained after cleaning.")

    working["date"] = working["date"].dt.normalize()
    working = working.sort_values("date").reset_index(drop=True)

    optional_present = sorted(set(column_map) - set(REQUIRED_FIELDS))
    LOG.info(
        "Loaded dataset %s: %s rows, %s products, optional fields present: %s",
        name, f"{len(working):,}", working["product"].nunique(),
        ", ".join(optional_present) or "none",
    )
    return Dataset(name=name, frame=working, column_map=column_map, warnings=warnings)


def load_csv(content: bytes, name: str) -> Dataset:
    return build_dataset(read_csv(content, name), name)
