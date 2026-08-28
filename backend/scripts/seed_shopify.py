#!/usr/bin/env python3
"""Push the bundled UCI dataset into a Shopify development store as real orders.

Why this exists
---------------
A "Connect Shopify" button is only convincing if there is something on the other
side of it. This script takes the real Online Retail II transactions the project
already ships and writes them into your own free Shopify development store as
genuine products and orders. The demo then runs the other way round: click
Connect, approve on Shopify's own consent screen, press Sync, and the forecast is
computed from data that just came back out of Shopify over the Admin API.

Nothing here is invented. Every order it creates carries a real date, a real
product title and a real quantity taken from the dataset.

Two ways to give it a token
---------------------------
Shopify changed this in January 2026, and the two routes now look quite different.

**A legacy custom app** (store admin -> Settings -> Apps and sales channels ->
Develop apps -> Allow legacy custom app development). Pick the Admin API scopes
``write_products``, ``write_orders`` and ``read_orders``, install it, and Shopify
shows you an Admin API access token starting with ``shpat_`` exactly once. Pass it
with ``--token``. Still available to Partners on a store they have not transferred
to a merchant.

**A Dev Dashboard app**, which never issues a token directly -- its Client ID and
secret are OAuth credentials, and the token only exists after the app is installed
through the OAuth flow. RetailIQ already performs that flow, so once you have
pressed Connect in the app you can seed with ``--from-connection`` and the token is
read straight out of the encrypted store. It is never printed or pasted anywhere.

Usage
-----
    python -m scripts.seed_shopify --shop my-store --token shpat_xxx --dry-run
    python -m scripts.seed_shopify --shop my-store --from-connection

Rate limits
-----------
Shopify's GraphQL API is metered by query cost, not request count. Order creation
is expensive, so this runs one order at a time with backoff. Roughly 400 orders
takes four to six minutes; that is the API's pace, not a limitation of the script.

Note on ``processedAt``
-----------------------
Backdated orders must set ``processedAt`` -- ``createdAt`` is assigned by Shopify
and would stamp every imported order with today's date, collapsing two years of
history into one day. The connector reads ``processedAt`` for exactly this reason.

Note on dates being shifted forward
-----------------------------------
The UCI dataset runs 2009-12 to 2011-12. A sync pulls a window measured backwards
from today, so seeding those true dates into a store in 2026 produces a store the
connector cannot see: the data is real but it sits fifteen years outside any
window worth requesting.

By default this script therefore **shifts the whole series forward** so the last
order lands yesterday. Every interval, quantity, price and product is untouched --
only the origin moves, and by exactly one constant. The shift is printed, recorded
in each order's note, and tagged ``retailiq-seed`` in Shopify, so nobody can later
mistake this for genuine 2026 trading. Pass ``--keep-original-dates`` to seed the
true 2010-2011 dates instead, and then sync with a matching ``?days=`` window.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV = REPO_ROOT / "data" / "retail_transactions.csv"
API_VERSION = "2025-01"

PRODUCT_CREATE = """
mutation CreateProduct($product: ProductCreateInput!) {
  productCreate(product: $product) {
    product { id title variants(first: 1) { nodes { id price } } }
    userErrors { field message }
  }
}
"""

# Deliberately does NOT select the created `order` back. Orders carry customer
# PII, so Shopify gates the Order *object* behind Protected Customer Data
# approval -- and selecting it makes an otherwise-permitted write fail with
# ACCESS_DENIED. We only need to know the write succeeded, which userErrors tells
# us. (Reading orders later still requires that approval; see the README.)
ORDER_CREATE = """
mutation CreateOrder($order: OrderCreateOrderInput!) {
  orderCreate(order: $order) {
    userErrors { field message }
  }
}
"""

SHOP_QUERY = "query { shop { name myshopifyDomain currencyCode } }"

# Shopify validates province against the country, so a wrong code rejects the order.
CITY_PROVINCE = {
    "Bengaluru": "KA", "Mumbai": "MH", "Delhi": "DL", "Hyderabad": "TG",
    "Chennai": "TN", "Pune": "MH", "Kolkata": "WB", "Ahmedabad": "GJ",
}

PRODUCTS_QUERY = """
query Existing($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { id title variants(first: 1) { nodes { id } } }
  }
}
"""

PRODUCT_DELETE = """
mutation Del($input: ProductDeleteInput!) {
  productDelete(input: $input) { deletedProductId userErrors { message } }
}
"""


class ShopifyAdmin:
    def __init__(self, shop: str, token: str) -> None:
        domain = shop.strip().lower().removeprefix("https://").removeprefix("http://")
        domain = domain.split("/")[0]
        if not domain.endswith(".myshopify.com"):
            domain = f"{domain}.myshopify.com"
        self.domain = domain
        self.url = f"https://{domain}/admin/api/{API_VERSION}/graphql.json"
        self.session = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
        })

    def call(self, query: str, variables: dict | None = None) -> dict:
        for attempt in range(6):
            try:
                response = self.session.post(
                    self.url, json={"query": query, "variables": variables or {}}, timeout=60
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                # A dropped connection part-way through a long import is a network
                # hiccup, not a reason to throw away twenty minutes of progress.
                wait = 5 * (attempt + 1)
                print(f"  network error ({type(exc).__name__}); retrying in {wait}s")
                time.sleep(wait)
                continue
            if response.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code == 401:
                sys.exit("Shopify rejected the token. Check --token and its scopes.")
            response.raise_for_status()
            payload = response.json()

            errors = payload.get("errors") or []
            codes = {(e.get("extensions") or {}).get("code") for e in errors}
            if "THROTTLED" in codes:
                time.sleep(2 * (attempt + 1))
                continue
            if errors:
                raise RuntimeError(json.dumps(errors, indent=2))
            return payload.get("data") or {}
        raise RuntimeError("Shopify kept throttling. Try again later.")


def shift_to_recent(daily: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Move the whole series forward so it ends yesterday, preserving every gap.

    One constant offset applied to every row. Weekday alignment is not preserved
    and is not claimed to be -- the point is to place real intervals inside a
    window the connector can actually request.
    """
    last = daily["Date"].max()
    target = pd.Timestamp(date.today() - timedelta(days=1))
    offset = (target - last).days
    shifted = daily.copy()
    shifted["Date"] = shifted["Date"] + pd.Timedelta(days=offset)
    return shifted, offset


def load_transactions(path: Path, products: int, days: int) -> pd.DataFrame:
    if not path.exists():
        sys.exit(
            f"{path} is missing. Rebuild it with:\n"
            "  cd backend && python -m scripts.build_dataset --out ../data"
        )
    frame = pd.read_csv(path)
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"])

    # The densest products give the most forecastable series, which is what makes
    # the demo worth watching.
    top = (
        frame.groupby("Product Name")["Units Sold"].sum()
        .sort_values(ascending=False).head(products).index.tolist()
    )
    frame = frame[frame["Product Name"].isin(top)]

    cutoff = frame["Date"].max() - pd.Timedelta(days=days)
    frame = frame[frame["Date"] >= cutoff]

    keys = ["Date", "Product Name"]
    if "Region" in frame.columns:
        # Keeping the city means one order per city per day, which is what lets the
        # connector reconstruct per-market demand after the round trip.
        keys.insert(1, "Region")
    daily = (
        frame.groupby(keys)
        .agg(units=("Units Sold", "sum"), price=("Unit Price", "mean"))
        .reset_index()
    )
    daily = daily[daily["units"] > 0]
    return daily


def existing_products(client: ShopifyAdmin) -> dict[str, list[dict]]:
    """Every product already in the store, grouped by title.

    Products are not customer data, so this read is permitted even before the
    Protected Customer Data approval that orders require.
    """
    by_title: dict[str, list[dict]] = {}
    cursor = None
    while True:
        data = client.call(PRODUCTS_QUERY, {"cursor": cursor})
        block = data.get("products") or {}
        for node in block.get("nodes") or []:
            by_title.setdefault(node["title"], []).append(node)
        page = block.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return by_title


def ensure_products(client: ShopifyAdmin, titles: list[str], prices: dict[str, float],
                    dry_run: bool) -> dict[str, str]:
    """Create the products, reusing any that already exist.

    A seeding run that dies part-way used to leave duplicates behind, and the next
    run added four more. Looking first makes the script safe to re-run, which is
    what you actually want from an importer.
    """
    variants: dict[str, str] = {}
    if dry_run:
        for index, title in enumerate(titles):
            print(f"  would create product  {title!r} at "
                  f"{max(prices.get(title, 1.0), 0.01):.2f}")
            variants[title] = f"gid://shopify/ProductVariant/dry-{index}"
        return variants

    present = existing_products(client)

    # Tidy up any duplicates a previous half-finished run left behind.
    for title in titles:
        extras = present.get(title, [])[1:]
        for node in extras:
            client.call(PRODUCT_DELETE, {"input": {"id": node["id"]}})
            print(f"  removed duplicate  {title}")
            time.sleep(0.3)
        if extras:
            present[title] = present[title][:1]

    for title in titles:
        found = present.get(title)
        if found:
            nodes = (found[0].get("variants") or {}).get("nodes") or []
            variants[title] = nodes[0]["id"] if nodes else ""
            print(f"  reused product     {title}")
            continue

        data = client.call(PRODUCT_CREATE, {"product": {
            "title": title,
            "productType": "Homeware",
            "status": "ACTIVE",
            "descriptionHtml": (
                "Imported from the UCI Online Retail II dataset for RetailIQ "
                "demonstration purposes."
            ),
        }})
        result = data.get("productCreate") or {}
        if result.get("userErrors"):
            raise RuntimeError(f"{title}: {result['userErrors']}")
        nodes = ((result.get("product") or {}).get("variants") or {}).get("nodes") or []
        if not nodes:
            raise RuntimeError(f"{title}: Shopify returned no default variant.")
        variants[title] = nodes[0]["id"]
        print(f"  created product    {title}")
        time.sleep(0.3)
    return variants


def checkpoint_path(shop: str) -> Path:
    """Where we record which days have been created for this store."""
    directory = REPO_ROOT / "data" / "connectors"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"seed-{shop.split('.')[0]}.json"


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text()).get("created_days", []))
    except Exception:
        return set()


def save_checkpoint(path: Path, days: set[str]) -> None:
    path.write_text(json.dumps({"created_days": sorted(days)}, indent=0))


def create_orders(client: ShopifyAdmin, daily: pd.DataFrame, currency: str,
                  dry_run: bool, shift_days: int = 0,
                  checkpoint: Path | None = None, pace: float = 1.5) -> tuple[int, int]:
    """Create one order per trading day, surviving Shopify's order-rate limiter.

    Two things make this more careful than it looks:

    **"Too many attempts" is not fatal.** Shopify rate-limits order creation
    separately from the GraphQL cost budget, and it answers with a ``userErrors``
    message rather than an HTTP 429. Treating that as an error aborts a run that
    would have succeeded thirty seconds later, so it backs off and retries.

    **Progress is checkpointed.** Orders carry customer data, which this app may
    not be allowed to read back, so the store cannot be asked what already exists.
    Recording each created day locally is what makes a re-run resume rather than
    duplicate.
    """
    created = 0
    skipped = 0
    done: set[str] = load_checkpoint(checkpoint) if checkpoint else set()
    by_city = "Region" in daily.columns
    grouped = list(daily.groupby(["Date", "Region"] if by_city else "Date"))
    total = len(grouped)

    for index, (group_key, rows) in enumerate(grouped, start=1):
        day, city = (group_key if by_city else (group_key, None))
        stamp = pd.Timestamp(day)
        key = f"{stamp.date().isoformat()}|{city}" if by_city else stamp.date().isoformat()
        if key in done:
            skipped += 1
            continue

        line_items = [{
            "title": row["Product Name"],
            "quantity": int(row["units"]),
            "priceSet": {"shopMoney": {
                "amount": f"{max(float(row['price']), 0.01):.2f}",
                "currencyCode": currency,
            }},
            "requiresShipping": False,
        } for _, row in rows.iterrows()]

        order = {
            # The real sale date. Without this every order lands on today.
            "processedAt": stamp.tz_localize("UTC").isoformat(),
            **({"shippingAddress": {
                "city": city, "countryCode": "IN", "address1": f"{city} store",
                "firstName": "RetailIQ", "lastName": "Demo", "zip": "560001",
                "provinceCode": CITY_PROVINCE.get(city, "KA"),
            }} if city else {}),
            "currency": currency,
            "lineItems": line_items,
            "financialStatus": "PAID",
            "tags": ["retailiq-seed"] + ([city] if city else []),
            "note": (
                "Seeded from the UCI Online Retail II dataset by RetailIQ."
                + (f" Dates shifted forward {shift_days} days from the original "
                   "2010-2011 series; quantities and intervals unchanged."
                   if shift_days else "")
            ),
        }

        if dry_run:
            if index <= 3:
                print(f"  would create order {key} with {len(line_items)} line item(s)")
            created += 1
            continue

        for attempt in range(6):
            data = client.call(ORDER_CREATE, {"order": order})
            errors = (data.get("orderCreate") or {}).get("userErrors") or []
            if not errors:
                break
            message = " ".join(str(e.get("message", "")) for e in errors)
            if "too many attempts" in message.lower() or "throttl" in message.lower():
                ladder = (5, 10, 20, 40, 60, 90)
                wait = ladder[min(attempt, len(ladder) - 1)]
                print(f"  rate-limited at {key}; waiting {wait}s "
                      f"(attempt {attempt + 1} of 6)")
                time.sleep(wait)
                continue
            raise RuntimeError(f"{key}: {errors}")
        else:
            print(f"\n  Shopify kept refusing at {key}. "
                  f"{created} order(s) were created and recorded.")
            print("  Re-run the same command later and it will resume from here.")
            break

        created += 1
        done.add(key)
        if checkpoint and created % 10 == 0:
            save_checkpoint(checkpoint, done)
        if index % 25 == 0 or index == total:
            print(f"  {index}/{total}  ({key})")
        time.sleep(pace)

    if checkpoint and not dry_run:
        save_checkpoint(checkpoint, done)
    return created, skipped


def token_from_connection(shop: str) -> str:
    """Read the access token RetailIQ already holds for this store.

    A Dev Dashboard app hands out no token of its own -- one only comes into
    existence when the app is installed through OAuth, which is precisely what the
    Connect button does. Rather than making anyone reveal and paste that token, we
    decrypt it in-process from the connection RetailIQ already stores.
    """
    from sqlalchemy import select

    from app.db.models import ConnectorAccount
    from app.db.session import session_scope
    from app.services.connectors import crypto

    wanted = shop.lower()
    with session_scope() as session:
        accounts = session.execute(
            select(ConnectorAccount).where(ConnectorAccount.provider == "shopify")
        ).scalars().all()
        rows = [(a.external_id or "", a.label, a.access_token_encrypted) for a in accounts]

    if not rows:
        sys.exit(
            "No Shopify account is connected yet.\n"
            "  Open RetailIQ -> Connect data -> Shopify, press Connect and approve on\n"
            "  Shopify's screen. Then run this again with --from-connection.\n"
            "  (Or use a legacy custom app's shpat_ token with --token.)"
        )

    matches = [r for r in rows if wanted in r[0].lower()] or rows
    if len(matches) > 1:
        listing = "\n".join(f"    {r[0]}  ({r[1]})" for r in matches)
        sys.exit(f"Several Shopify connections match '{shop}':\n{listing}\n"
                 "  Pass the full domain to --shop to pick one.")

    external_id, label, encrypted = matches[0]
    token = crypto.decrypt(encrypted)
    if not token:
        sys.exit(
            "That connection's token could not be decrypted, which happens when\n"
            "  RETAILIQ_SECRET_KEY changed or was never set. Reconnect the store."
        )
    print(f"Token     read from the connected account '{label}' ({external_id})")
    return token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--shop", required=True, help="Store domain, e.g. my-store")
    parser.add_argument("--token", help="Admin API access token (shpat_...) from a "
                                        "legacy custom app")
    parser.add_argument("--from-connection", action="store_true",
                        help="Use the token RetailIQ already holds for this store, "
                             "obtained when you pressed Connect. Nothing is printed.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--products", type=int, default=4,
                        help="How many of the densest products to seed (default 4)")
    parser.add_argument("--days", type=int, default=400,
                        help="How many days of history to seed (default 400)")
    parser.add_argument("--keep-original-dates", action="store_true",
                        help="Seed the true 2010-2011 dates. The store will then hold "
                             "data no ordinary sync window reaches -- you must pass a "
                             "matching ?days= when syncing.")
    parser.add_argument("--pace", type=float, default=1.5,
                        help="Seconds between orders. Shopify rate-limits order "
                             "creation hard; raise this if you keep getting backed off.")
    parser.add_argument("--fresh", action="store_true",
                        help="Ignore the checkpoint and create every day again. Only "
                             "use this on a store you have emptied.")
    parser.add_argument("--cities", type=int, default=0,
                        help="Keep only the N busiest cities. 0 keeps all of them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without calling Shopify")
    args = parser.parse_args()

    if bool(args.token) == bool(args.from_connection):
        parser.error(
            "Give exactly one of --token (a shpat_... token from a legacy custom app) "
            "or --from-connection (reuse the token from pressing Connect in RetailIQ)."
        )

    daily = load_transactions(args.csv, args.products, args.days)
    if args.cities and "Region" in daily.columns:
        busiest = (daily.groupby("Region")["units"].sum()
                   .sort_values(ascending=False).head(args.cities).index)
        daily = daily[daily["Region"].isin(busiest)]
        print(f"  Limited to {args.cities} cities: {', '.join(busiest)}")
    titles = sorted(daily["Product Name"].unique())
    prices = daily.groupby("Product Name")["price"].mean().to_dict()

    print(f"\nDataset  {args.csv}")
    print(f"  {len(titles)} products, {daily['Date'].nunique()} trading days, "
          f"{int(daily['units'].sum()):,} units")
    print(f"  {daily['Date'].min().date()} to {daily['Date'].max().date()}")

    shift_days = 0
    if args.keep_original_dates:
        window = (date.today() - daily["Date"].min().date()).days + 1
        print("\n  Keeping the original dates. Note that these orders sit outside an")
        print(f"  ordinary sync window -- sync with ?days={window} or more to see them.")
    else:
        daily, shift_days = shift_to_recent(daily)
        print(f"\n  Dates shifted forward {shift_days:,} days so the history ends "
              "yesterday.")
        print(f"  Now {daily['Date'].min().date()} to {daily['Date'].max().date()}. "
              "Quantities,")
        print("  intervals and products are unchanged; only the origin moved. Every")
        print("  order is tagged 'retailiq-seed' and says so in its note.")
    print()

    token = args.token or token_from_connection(args.shop)
    client = ShopifyAdmin(args.shop, token)
    currency = "GBP"
    if not args.dry_run:
        shop = (client.call(SHOP_QUERY).get("shop") or {})
        currency = shop.get("currencyCode", "GBP")
        print(f"Store    {shop.get('name')} ({shop.get('myshopifyDomain')}), {currency}\n")

    print("Products")
    variants = ensure_products(client, titles, prices, args.dry_run)
    print(f"  {len(variants)} ready\n")

    print("Orders")
    checkpoint = None if args.dry_run else checkpoint_path(args.shop)
    if checkpoint and args.fresh and checkpoint.exists():
        checkpoint.unlink()
        print("Checkpoint cleared; every day will be created again.\n")

    count, skipped = create_orders(
        client, daily, currency, args.dry_run, shift_days, checkpoint, args.pace
    )

    print(f"\n{'Would create' if args.dry_run else 'Created'} {count} orders "
          f"spanning {daily['Date'].nunique()} days."
          + (f" {skipped} already existed and were skipped." if skipped else ""))
    if not args.dry_run:
        print(
            "\nNext: open RetailIQ, go to Connect data, choose Shopify, enter\n"
            f"  {args.shop}\n"
            "approve on Shopify's consent screen, then press Sync.\n"
            "\nIf the sync returns only the last 60 days, that is the read_orders\n"
            "scope limit -- enable read_all_orders on the app and reconnect."
        )


if __name__ == "__main__":
    main()
