"""Build the RetailIQ benchmark dataset from the UCI Online Retail II archive.

Source
------
Chen, D. (2019). *Online Retail II* [Dataset]. UCI Machine Learning Repository.
https://doi.org/10.24432/C5CG6D

1,067,371 real transaction lines from a UK-based online giftware retailer,
2009-12-01 to 2011-12-09. This is genuine transactional data -- no values are
invented by this script.

What this script derives (and how)
----------------------------------
The source has 8 columns; the project schema wants more. Every derived column is
computed from real text already present in the source:

* ``Product Category`` -- keyword taxonomy applied to ``Description``. A product
  matching no keyword is labelled ``Uncategorised`` rather than guessed at.
* ``Color`` -- colour word extracted from ``Description`` (these products
  literally carry the colour in their name, e.g. "PINK CHERRY LIGHTS"). Products
  with no colour word are labelled ``Unspecified``.
* ``Total Revenue`` -- ``Quantity * Price``, an arithmetic identity.

``Payment Method`` does **not** exist in the source and is deliberately NOT
emitted. Inventing it would be fabrication. The ingestion layer treats it as an
optional column precisely so real-world CSVs like this one are accepted.

Cleaning rules (all documented, none silent)
--------------------------------------------
* Cancellation invoices (``Invoice`` starting with ``C``) are dropped -- they are
  returns, not demand.
* Non-product stock codes (postage, bank charges, manual adjustments, samples,
  test rows) are dropped via an explicit blocklist.
* Rows with non-positive ``Quantity`` or ``Price`` are dropped.
* Rows with a null ``Description`` are dropped.

Usage
-----
    python -m scripts.build_dataset --out ../data
    python -m scripts.build_dataset --out ../data --top-products 40 --full
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

LOG = logging.getLogger("build_dataset")

SOURCE_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
SOURCE_XLSX = "online_retail_II.xlsx"

# Stock codes that are not sellable products. Checked case-insensitively against
# the whole code, so real product codes such as "85048" are unaffected.
NON_PRODUCT_CODES = {
    "POST", "DOT", "D", "M", "S", "B", "CRUK", "PADS", "C2", "C3",
    "BANK CHARGES", "AMAZONFEE", "ADJUST", "ADJUST2", "TEST001", "TEST002",
    "GIFT", "SP1002", "m", "DCGS0076", "DCGS0003",
}

# Keyword taxonomy. Order matters: the first category whose keywords match wins,
# so seasonal lines are captured before the generic homeware buckets.
CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Christmas & Seasonal", (
        "christmas", "xmas", "advent", "santa", "reindeer", "snowman", "nativity",
        "easter", "halloween", "valentine", "mistletoe", "wreath", "bauble",
    )),
    ("Kitchen & Dining", (
        "mug", "plate", "bowl", "cake", "baking", "bake", "teapot", "cup",
        "jug", "tray", "cutlery", "napkin", "placemat", "coaster", "apron",
        "jar", "tin ", "kitchen", "cookie", "biscuit", "egg cup", "tea ",
        "colander", "whisk", "recipe", "lunch box", "bottle", "flask",
    )),
    ("Home Decor", (
        "t-light", "tlight", "tealight", "candle", "lantern", "ornament",
        "frame", "clock", "cushion", "hanging", "decoration", "mirror",
        "vase", "hook", "doorstop", "wall art", "sign", "heart", "chandelier",
        "lamp", "light", "drawer knob", "curtain",
    )),
    ("Bags & Storage", (
        "bag", "storage", "basket", "box", "case", "purse", "holdall",
        "trunk", "crate", "hamper", "sack",
    )),
    ("Stationery & Craft", (
        "card", "paper", "pen", "pencil", "notebook", "craft", "sticker",
        "wrap", "ribbon", "tissue", "chalkboard", "journal", "envelope",
        "stamp", "sketchbook", "eraser", "rubber", "glitter", "sewing",
    )),
    ("Toys & Games", (
        "toy", "game", "puzzle", "glider", "playhouse", "doll", "jigsaw",
        "skittle", "spinning top", "kids", "children", "bingo", "yoyo",
        "yo-yo", "marbles", "balloon", "harmonica", "soldier", "dinosaur",
    )),
    ("Garden & Outdoor", (
        "garden", "plant", "watering", "birdhouse", "bird feeder", "parasol",
        "deckchair", "picnic", "windmill", "thermometer", "wheelbarrow",
    )),
    ("Jewellery & Accessories", (
        "necklace", "bracelet", "earring", " ring", "scarf", "hair", "brooch",
        "umbrella", "glove", "slipper", "wallet", "keyring", "charm",
        "sunglasses", "hat", "tie",
    )),
    ("Bath & Wellbeing", (
        "soap", "bath", "towel", "hot water bottle", "incense", "lavender",
        "flannel", "sponge",
    )),
]

# Colour words that genuinely appear in this catalogue's product names.
COLOR_WORDS = (
    "red", "pink", "blue", "white", "black", "green", "ivory", "cream",
    "silver", "gold", "purple", "orange", "yellow", "brown", "grey", "gray",
    "turquoise", "beige", "natural", "clear", "rose", "lilac", "burgundy",
    "aqua", "mint", "amber", "bronze", "copper", "navy", "coral",
)
COLOR_RE = re.compile(r"\b(" + "|".join(COLOR_WORDS) + r")\b", re.IGNORECASE)

OUTPUT_COLUMNS = [
    "Transaction ID", "Date", "Product Category", "Product Name", "Color",
    "Units Sold", "Unit Price", "Total Revenue", "Region",
]


def download_source(raw_dir: Path) -> Path:
    """Fetch and unpack the UCI archive, skipping work already done."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = raw_dir / SOURCE_XLSX
    if xlsx_path.exists():
        LOG.info("Using cached source workbook at %s", xlsx_path)
        return xlsx_path

    zip_path = raw_dir / "online_retail_II.zip"
    if not zip_path.exists():
        LOG.info("Downloading %s (~44 MB)", SOURCE_URL)
        response = requests.get(SOURCE_URL, timeout=600, stream=True)
        response.raise_for_status()
        with zip_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)

    LOG.info("Extracting %s", zip_path.name)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extract(SOURCE_XLSX, path=raw_dir)
    return xlsx_path


def load_source(xlsx_path: Path) -> pd.DataFrame:
    """Read both year sheets into a single frame."""
    LOG.info("Reading workbook (this takes ~60s for 1.07M rows)")
    workbook = pd.ExcelFile(xlsx_path)
    frame = pd.concat(
        [workbook.parse(sheet) for sheet in workbook.sheet_names],
        ignore_index=True,
    )
    LOG.info("Loaded %s raw transaction lines", f"{len(frame):,}")
    return frame


def classify_category(description: str) -> str:
    lowered = f" {description.lower()} "
    for category, keywords in CATEGORY_RULES:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "Uncategorised"


def extract_color(description: str) -> str:
    match = COLOR_RE.search(description)
    if not match:
        return "Unspecified"
    word = match.group(1).lower()
    return "Grey" if word == "gray" else word.title()


def clean(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the documented cleaning rules, logging how much each one removes."""
    start = len(frame)
    frame = frame.dropna(subset=["Description", "Invoice", "StockCode"]).copy()

    frame["Invoice"] = frame["Invoice"].astype(str).str.strip()
    frame["StockCode"] = frame["StockCode"].astype(str).str.strip()
    frame["Description"] = frame["Description"].astype(str).str.strip()

    cancellations = frame["Invoice"].str.upper().str.startswith("C")
    LOG.info("Dropping %s cancellation lines", f"{int(cancellations.sum()):,}")
    frame = frame[~cancellations]

    blocked = frame["StockCode"].str.upper().isin({c.upper() for c in NON_PRODUCT_CODES})
    LOG.info(
        "Dropping %s non-product lines (postage, fees, adjustments)",
        f"{int(blocked.sum()):,}",
    )
    frame = frame[~blocked]

    invalid = (frame["Quantity"] <= 0) | (frame["Price"] <= 0)
    LOG.info("Dropping %s lines with non-positive quantity or price", f"{int(invalid.sum()):,}")
    frame = frame[~invalid]

    frame["InvoiceDate"] = pd.to_datetime(frame["InvoiceDate"])
    LOG.info(
        "Retained %s of %s lines (%.1f%%)",
        f"{len(frame):,}", f"{start:,}", 100 * len(frame) / start,
    )
    return frame


def to_project_schema(frame: pd.DataFrame) -> pd.DataFrame:
    """Map the cleaned source onto the RetailIQ transaction schema."""
    LOG.info("Deriving category and colour from product descriptions")
    descriptions = frame["Description"].str.title()
    unique = pd.Series(frame["Description"].unique())
    category_map = dict(zip(unique, unique.map(classify_category), strict=True))
    color_map = dict(zip(unique, unique.map(extract_color), strict=True))

    out = pd.DataFrame({
        "Transaction ID": frame["Invoice"].astype(str),
        "Date": frame["InvoiceDate"].dt.strftime("%Y-%m-%d"),
        "Product Category": frame["Description"].map(category_map),
        "Product Name": descriptions,
        "Color": frame["Description"].map(color_map),
        "Units Sold": frame["Quantity"].astype(int),
        "Unit Price": frame["Price"].round(2),
        "Region": frame["Country"].astype(str),
    })
    out["Total Revenue"] = (out["Units Sold"] * out["Unit Price"]).round(2)
    return out[OUTPUT_COLUMNS].sort_values(["Date", "Transaction ID"]).reset_index(drop=True)


def select_products(frame: pd.DataFrame, top_products: int) -> pd.DataFrame:
    """Keep the products with the densest daily coverage.

    Ranking by *distinct selling days* rather than total units picks series that
    are actually forecastable, instead of one-off bulk orders that happen to have
    a huge quantity on a single day.
    """
    coverage = (
        frame.groupby("Product Name")["Date"].nunique()
        .sort_values(ascending=False)
        .head(top_products)
    )
    LOG.info(
        "Selected %d products; daily coverage ranges %d-%d days",
        len(coverage), coverage.min(), coverage.max(),
    )
    return frame[frame["Product Name"].isin(coverage.index)].reset_index(drop=True)


def summarise(frame: pd.DataFrame) -> None:
    dates = pd.to_datetime(frame["Date"])
    daily = frame.groupby("Date")["Units Sold"].sum()
    daily.index = pd.to_datetime(daily.index)
    dow = daily.groupby(daily.index.dayofweek).mean()
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    LOG.info("--- dataset summary ---")
    LOG.info(
        "rows=%s  products=%d  regions=%d", f"{len(frame):,}",
        frame["Product Name"].nunique(), frame["Region"].nunique(),
    )
    LOG.info(
        "date range %s -> %s (%d calendar days, %d with sales)",
        dates.min().date(), dates.max().date(),
        (dates.max() - dates.min()).days + 1, daily.size,
    )
    LOG.info(
        "categories: %s", ", ".join(sorted(frame["Product Category"].unique()))
    )
    LOG.info(
        "mean units/day by weekday: %s",
        "  ".join(f"{names[d]}={v:,.0f}" for d, v in dow.items()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("../data"),
                        help="output directory (default: ../data)")
    parser.add_argument("--top-products", type=int, default=30,
                        help="products to keep in the curated sample (default: 30)")
    parser.add_argument("--full", action="store_true",
                        help="additionally write the full cleaned dataset (~90 MB)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    out_dir: Path = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    xlsx_path = download_source(out_dir / "raw")
    projected = to_project_schema(clean(load_source(xlsx_path)))

    if args.full:
        full_path = out_dir / "retail_transactions_full.csv"
        projected.to_csv(full_path, index=False)
        LOG.info("Wrote full dataset -> %s (%.1f MB)",
                 full_path, full_path.stat().st_size / 1e6)

    sample = select_products(projected, args.top_products)
    sample_path = out_dir / "retail_transactions.csv"
    sample.to_csv(sample_path, index=False)
    LOG.info("Wrote curated sample -> %s (%.1f MB)",
             sample_path, sample_path.stat().st_size / 1e6)
    summarise(sample)
    return 0


if __name__ == "__main__":
    sys.exit(main())
