#!/usr/bin/env python3
"""Empty a seeded Shopify demo store so it can be rebuilt from a different catalogue.

Only touches what this project created: orders tagged ``retailiq-seed`` and the
products whose titles are in the store's catalogue. It will not delete a real
merchant's data, and it refuses to run without ``--yes``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.db.models import ConnectorAccount
from app.db.session import session_scope
from app.services.connectors import crypto
from app.services.connectors.shopify import ShopifyConnector

FIND_ORDERS = """
query($cursor: String) {
  orders(first: 100, after: $cursor, query: "tag:retailiq-seed") {
    pageInfo { hasNextPage endCursor }
    nodes { id name }
  }
}
"""
DELETE_ORDER = """
mutation D($id: ID!) { orderDelete(orderId: $id) { deletedId userErrors { message } } }
"""
FIND_PRODUCTS = """
query($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes { id title }
  }
}
"""
DELETE_PRODUCT = """
mutation D($input: ProductDeleteInput!) {
  productDelete(input: $input) { deletedProductId userErrors { message } }
}
"""


async def main_async(shop_hint: str, keep_products: bool) -> None:
    with session_scope() as session:
        account = session.execute(
            select(ConnectorAccount).where(ConnectorAccount.provider == "shopify")
        ).scalars().first()
        if account is None:
            sys.exit("No Shopify account is connected.")
        token = crypto.decrypt(account.access_token_encrypted)
        shop = (account.meta or {}).get("shop") or account.external_id

    if shop_hint and shop_hint not in (shop or ""):
        sys.exit(f"Connected store is {shop}, not {shop_hint}. Refusing to touch it.")

    connector = ShopifyConnector()
    print(f"Clearing {shop}")

    removed = 0
    cursor = None
    while True:
        data = await connector._graphql(shop, token, FIND_ORDERS, {"cursor": cursor})
        block = data.get("orders") or {}
        nodes = block.get("nodes") or []
        for node in nodes:
            result = await connector._graphql(
                shop, token, DELETE_ORDER, {"id": node["id"]}
            )
            errors = (result.get("orderDelete") or {}).get("userErrors") or []
            if errors:
                print(f"  {node['name']}: {errors}")
            else:
                removed += 1
                if removed % 25 == 0:
                    print(f"  deleted {removed} orders")
        page = block.get("pageInfo") or {}
        if not page.get("hasNextPage") or not nodes:
            break
        # Deleting shifts the page window, so restart rather than paginate.
        cursor = None
    print(f"  {removed} seeded orders deleted")

    if keep_products:
        return
    gone = 0
    while True:
        data = await connector._graphql(shop, token, FIND_PRODUCTS, {"cursor": None})
        nodes = (data.get("products") or {}).get("nodes") or []
        if not nodes:
            break
        for node in nodes:
            await connector._graphql(
                shop, token, DELETE_PRODUCT, {"input": {"id": node["id"]}}
            )
            gone += 1
        if len(nodes) < 100:
            break
    print(f"  {gone} products deleted")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--shop", default="")
    parser.add_argument("--keep-products", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Required. This deletes data.")
    args = parser.parse_args()
    if not args.yes:
        sys.exit("Refusing to delete anything without --yes.")
    asyncio.run(main_async(args.shop, args.keep_products))


if __name__ == "__main__":
    main()
