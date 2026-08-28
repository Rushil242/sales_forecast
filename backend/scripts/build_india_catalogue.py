#!/usr/bin/env python3
"""Generate a synthetic Indian fast-fashion transaction dataset.

READ THIS BEFORE QUOTING ANY RESULT FROM IT
===========================================
This data is **generated, not observed**. Every other dataset in RetailIQ is real
(the bundled UCI Online Retail II file, an uploaded CSV, a live Shopify sync). This
one is not, and it must be labelled that way everywhere it appears, because the
whole point of this project is that its numbers are measured rather than asserted.

Why it exists anyway: the UCI data is a UK giftware wholesaler selling t-light
holders. It cannot support the story an Indian apparel retailer needs -- there is no
Bangalore, no hoodie, no Diwali. A clearly-labelled simulation is the honest way to
demonstrate the product on that shape of business; quietly relabelling UK giftware
as Indian clothing would not be.

**The one caveat that matters at a review.** The generator deliberately writes
temperature and festival effects into demand. So when the covariate selector then
reports "weather helps", it is partly rediscovering a pattern that was put there on
purpose. That is a legitimate way to show the mechanism working end to end, but it
is NOT evidence that weather helps real apparel demand. On the real UCI data the
same selector keeps holidays and weather on some series and rejects them on others,
and *that* is the honest measurement to quote.

What is modelled
----------------
* Eight metros with their own climate, so a hoodie sells in Delhi in January and
  barely moves in Chennai. Temperature drives warm-wear up and summer-wear down.
* The Indian festival calendar (Diwali, Navratri, Holi, Eid, wedding season) lifts
  ethnic and occasion wear far more than basics.
* Weekend uplift, because this is a consumer chain rather than the UK wholesaler in
  the bundled file -- whose demand, measurably, *falls* 69% at weekends.
* Payday: a bump in the first week of the month, which is a real feature of Indian
  salaried retail.
* Per-store scale, a gentle growth trend, and Poisson-ish noise so no two days match.
"""

from __future__ import annotations

import argparse
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── the chain ────────────────────────────────────────────────────────────────
# Monthly mean daytime temperature (°C), roughly true to each city, which is what
# makes warm-wear regional rather than uniform.
CITIES: dict[str, dict] = {
    "Bengaluru": {"scale": 1.00, "temps": [27, 30, 33, 34, 33, 29, 28, 28, 29, 29, 27, 26]},
    "Mumbai":    {"scale": 1.25, "temps": [31, 32, 33, 34, 34, 32, 30, 30, 31, 34, 34, 32]},
    "Delhi":     {"scale": 1.15, "temps": [19, 23, 29, 36, 40, 39, 35, 34, 34, 32, 27, 21]},
    "Hyderabad": {"scale": 0.85, "temps": [29, 32, 36, 38, 39, 34, 31, 30, 31, 31, 29, 28]},
    "Chennai":   {"scale": 0.80, "temps": [30, 32, 34, 36, 38, 37, 35, 35, 34, 32, 30, 29]},
    "Pune":      {"scale": 0.70, "temps": [30, 33, 36, 38, 38, 33, 29, 28, 30, 32, 30, 29]},
    "Kolkata":   {"scale": 0.75, "temps": [26, 30, 34, 36, 36, 34, 32, 32, 32, 32, 30, 27]},
    "Ahmedabad": {"scale": 0.65, "temps": [28, 31, 36, 40, 41, 38, 33, 32, 34, 36, 33, 29]},
}

# thermal: +1 = sells more when cold, -1 = sells more when hot, 0 = year-round.
# festival: how strongly the item lifts around Diwali / weddings / Navratri.
PRODUCTS: list[dict] = [
    # ── Men · Topwear ──
    ("Oversized Cotton Tee",        "Men · Topwear",    349,  -0.6, 0.2, 1.00),
    ("Linen Blend Casual Shirt",    "Men · Topwear",    999,  -0.8, 0.5, 0.70),
    ("Zip-Up Hoodie",               "Men · Topwear",   1299,   1.0, 0.1, 0.55),
    ("Pique Polo T-Shirt",          "Men · Topwear",    599,  -0.3, 0.3, 0.75),
    # ── Men · Bottomwear ──
    ("Slim Fit Chinos",             "Men · Bottomwear", 1199,  0.0, 0.3, 0.60),
    ("Straight Fit Denim Jeans",    "Men · Bottomwear", 1499,  0.2, 0.3, 0.85),
    ("Cargo Joggers",               "Men · Bottomwear",  899,  0.3, 0.1, 0.65),
    # ── Women · Topwear ──
    ("Rayon Crop Top",              "Women · Topwear",   399, -0.7, 0.3, 0.90),
    ("Printed A-Line Kurti",        "Women · Topwear",   799, -0.2, 0.9, 1.10),
    ("Ribbed Knit Top",             "Women · Topwear",   549,  0.4, 0.2, 0.60),
    ("Oversized Sweatshirt",        "Women · Topwear",  1099,  1.0, 0.1, 0.55),
    # ── Women · Bottomwear ──
    ("High-Rise Skinny Jeans",      "Women · Bottomwear", 1399, 0.2, 0.3, 0.80),
    ("Flowy Palazzo Pants",         "Women · Bottomwear",  699, -0.6, 0.4, 0.60),
    ("Pleated Midi Skirt",          "Women · Bottomwear",  899, -0.4, 0.4, 0.45),
    # ── Outerwear ──
    ("Puffer Jacket",               "Outerwear",        2499,  1.4, 0.2, 0.35),
    ("Denim Jacket",                "Outerwear",        1799,  0.7, 0.3, 0.40),
    # ── Ethnic & Occasion ──
    ("Anarkali Kurta Set",          "Ethnic & Occasion", 1999, -0.1, 1.6, 0.50),
    ("Cotton Handloom Saree",       "Ethnic & Occasion", 1599, -0.3, 1.4, 0.40),
    ("Nehru Jacket",                "Ethnic & Occasion", 1499,  0.4, 1.3, 0.30),
    ("Embroidered Sherwani",        "Ethnic & Occasion", 3499,  0.2, 1.8, 0.15),
]

# Approximate dates of the festivals that actually move Indian apparel. Real dates
# are lunar and shift each year, so these are the observed dates for the years the
# generator covers rather than a formula.
FESTIVALS: dict[str, list[tuple[int, int]]] = {
    "diwali":    [(2024, 11, 1), (2025, 10, 21), (2026, 11, 8)],
    "navratri":  [(2024, 10, 3), (2025, 9, 22), (2026, 10, 11)],
    "holi":      [(2024, 3, 25), (2025, 3, 14), (2026, 3, 4)],
    "eid":       [(2024, 4, 11), (2025, 3, 31), (2026, 3, 20)],
    "wedding_1": [(2024, 11, 25), (2025, 11, 25), (2026, 11, 25)],
    "wedding_2": [(2025, 2, 10), (2026, 2, 10), (2027, 2, 10)],
}


def _festival_lift(day: date) -> float:
    """How much the whole catalogue lifts today because of a festival.

    Shopping happens in the two to three weeks *before* the day itself, so the
    window is deliberately asymmetric.
    """
    lift = 0.0
    for name, occurrences in FESTIVALS.items():
        for y, m, d in occurrences:
            event = date(y, m, d)
            lead = (event - day).days
            if -2 <= lead <= 21:
                peak = 1.0 - (abs(lead - 5) / 16.0)
                strength = 1.4 if name == "diwali" else 0.9 if name.startswith("wedding") else 0.7
                lift = max(lift, max(0.0, peak) * strength)
    return lift


def _temperature(city: str, day: date) -> float:
    """Smooth daily temperature by interpolating between monthly means."""
    temps = CITIES[city]["temps"]
    month = day.month - 1
    nxt = (month + 1) % 12
    days_in_month = 30.4
    frac = (day.day - 1) / days_in_month
    base = temps[month] * (1 - frac) + temps[nxt] * frac
    # A small deterministic wobble so the series is not unnaturally smooth.
    return base + 2.2 * math.sin(day.toordinal() * 0.7)


def generate(start: date, end: date, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    total_days = (end - start).days + 1

    for offset in range(total_days):
        day = start + timedelta(days=offset)
        festival = _festival_lift(day)
        # Consumer retail is busier at weekends -- the opposite of the bundled UK
        # wholesaler, and worth contrasting in a review.
        weekend = 1.35 if day.weekday() >= 5 else 1.0
        payday = 1.18 if day.day <= 7 else 1.0
        trend = 1.0 + 0.00025 * offset

        for city, meta in CITIES.items():
            temp = _temperature(city, day)
            # Centre on 30C: positive when cold, negative when hot.
            cold = (30.0 - temp) / 10.0

            for name, category, price, thermal, festival_beta, popularity in PRODUCTS:
                base = 6.0 * meta["scale"] * popularity * trend * weekend * payday
                seasonal = max(0.15, 1.0 + thermal * cold)
                occasion = 1.0 + festival_beta * festival
                mean = base * seasonal * occasion
                units = int(rng.poisson(max(0.05, mean)))
                if units <= 0:
                    continue
                txn = f"T{day.strftime('%Y%m%d')}-{city[:3].upper()}"
                rows.append({
                    "Date": day.isoformat(),
                    "Product Name": name,
                    "Product Category": category,
                    "Units Sold": units,
                    "Unit Price": price,
                    "Total Revenue": units * price,
                    "Region": city,
                    "Transaction ID": txn,
                })

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--start", default="2024-09-01")
    parser.add_argument("--end", default="2026-08-25")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "india_apparel.csv")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    frame = generate(date.fromisoformat(args.start), date.fromisoformat(args.end), args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)

    print(f"\nWrote {args.out}")
    print(f"  {len(frame):,} rows · {frame['Product Name'].nunique()} products · "
          f"{frame['Region'].nunique()} cities")
    print(f"  {frame['Date'].min()} to {frame['Date'].max()}")
    print(f"  {int(frame['Units Sold'].sum()):,} units · "
          f"₹{frame['Total Revenue'].sum():,.0f} revenue")
    print("\n  THIS DATA IS GENERATED, NOT OBSERVED. It is labelled as such in the app.")
    top = frame.groupby("Product Name")["Units Sold"].sum().sort_values(ascending=False)
    print("\n  Top products:")
    for name, units in top.head(5).items():
        print(f"    {name:32s} {int(units):>8,}")


if __name__ == "__main__":
    main()
