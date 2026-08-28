"""The connect gallery: every platform we list, and what is actually true of each.

Only two providers here have a real integration behind them -- Shopify and Zoho.
That is a deliberate, defensible choice rather than a shortfall. Both expose a
public OAuth app any developer can register for free, which is what makes a
genuine "click the logo, land on their consent screen" flow possible.

The rest are listed with ``integration="csv"``, and each carries the real menu
path for exporting order history out of that platform. That is not a placeholder:
Tally is desktop software with no cloud API at all, WooCommerce issues per-store
keys rather than central OAuth credentials, and Amazon's SP-API requires an
approved developer profile. For those platforms a CSV export genuinely is how a
retailer gets their data out, so that is what we tell them to do.

What this file will never contain is a logo wired to invented orders.
"""

from __future__ import annotations

from app.services.connectors.base import ProviderSpec

PROVIDERS: tuple[ProviderSpec, ...] = (
    # ── real integrations ────────────────────────────────────────────────────
    ProviderSpec(
        key="shopify",
        name="Shopify",
        category="ecommerce",
        region="global",
        integration="live",
        auth="oauth",
        summary="Pull real order history straight from your Shopify store.",
        pulls=("Orders and line items", "Product titles and SKUs",
               "Quantities, prices and currency", "Shipping country"),
        csv_route="Shopify admin → Orders → Export → CSV for all orders.",
        docs_url="https://shopify.dev/docs/api/admin-graphql",
        credentials=("RETAILIQ_SHOPIFY_API_KEY", "RETAILIQ_SHOPIFY_API_SECRET"),
        mark="Sh",
        accent="#5E8E3E",
    ),
    ProviderSpec(
        key="zoho",
        name="Zoho Books / Inventory",
        category="accounting",
        region="india",
        integration="live",
        auth="oauth",
        summary="India's most-used SMB accounting suite. Invoices become demand history.",
        pulls=("Invoices and line items", "Item names and rates",
               "Quantities and totals", "Customer place of supply"),
        csv_route="Zoho Books → Sales → Invoices → ⋯ → Export → CSV.",
        docs_url="https://www.zoho.com/books/api/v3/",
        credentials=("RETAILIQ_ZOHO_CLIENT_ID", "RETAILIQ_ZOHO_CLIENT_SECRET"),
        mark="Zo",
        accent="#E42527",
    ),

    # ── documented CSV routes ────────────────────────────────────────────────
    ProviderSpec(
        key="woocommerce",
        name="WooCommerce",
        category="ecommerce",
        region="global",
        integration="csv",
        auth="csv",
        summary="Self-hosted WordPress stores issue per-store API keys, so there is "
                "no central app to authorise. Export takes about a minute.",
        pulls=("Orders", "Line items", "Product names"),
        csv_route="WordPress admin → WooCommerce → Analytics → Orders → "
                  "set the date range → Download.",
        docs_url="https://woocommerce.github.io/woocommerce-rest-api-docs/",
        mark="Wo",
        accent="#7F54B3",
    ),
    ProviderSpec(
        key="razorpay",
        name="Razorpay",
        category="payments",
        region="india",
        integration="csv",
        auth="csv",
        summary="Payments carry amounts but usually not product lines, so a Razorpay "
                "export forecasts revenue rather than units unless you record items "
                "in payment notes.",
        pulls=("Payment amounts", "Timestamps", "Item notes, when your checkout sets them"),
        csv_route="Razorpay Dashboard → Transactions → Payments → filter the period → "
                  "Download → CSV.",
        docs_url="https://razorpay.com/docs/api/",
        mark="Rz",
        accent="#0C2451",
    ),
    ProviderSpec(
        key="unicommerce",
        name="Unicommerce",
        category="marketplace",
        region="india",
        integration="csv",
        auth="csv",
        summary="Multi-channel order management. Its export already merges Amazon, "
                "Flipkart and your own site into one file.",
        pulls=("Sale orders across channels", "SKU and quantity", "Channel of sale"),
        csv_route="Unicommerce → Reports → Sale Report → choose the range → Export.",
        docs_url="https://docs.unicommerce.com/",
        mark="Un",
        accent="#F26522",
    ),
    ProviderSpec(
        key="tally",
        name="Tally Prime",
        category="accounting",
        region="india",
        integration="csv",
        auth="csv",
        summary="Tally runs on the shop's own machine and has no cloud API, so nothing "
                "can connect to it over the internet. The Sales Register export is the "
                "honest route.",
        pulls=("Sales register entries", "Stock item names", "Billed quantities"),
        csv_route="Gateway of Tally → Display More Reports → Account Books → "
                  "Sales Register → Alt+E → Export → CSV.",
        docs_url="https://help.tallysolutions.com/",
        mark="Ta",
        accent="#1B4F9C",
    ),
    ProviderSpec(
        key="vyapar",
        name="Vyapar",
        category="accounting",
        region="india",
        integration="csv",
        auth="csv",
        summary="Popular with small Indian retailers. No public API, but the sale "
                "report exports cleanly.",
        pulls=("Sale invoices", "Item names", "Quantities and rates"),
        csv_route="Vyapar → Reports → Sale → Sale Report → set the period → "
                  "Export to Excel.",
        docs_url="https://vyaparapp.in/",
        mark="Vy",
        accent="#1E88E5",
    ),
    ProviderSpec(
        key="mybillbook",
        name="myBillBook",
        category="accounting",
        region="india",
        integration="csv",
        auth="csv",
        summary="Mobile-first billing used by kirana and small retail. Export from the "
                "web dashboard rather than the app.",
        pulls=("Sales invoices", "Item-wise quantities"),
        csv_route="myBillBook web → Reports → Item-wise Sales → select the period → "
                  "Download.",
        docs_url="https://mybillbook.in/",
        mark="mB",
        accent="#00875A",
    ),
    ProviderSpec(
        key="amazon-seller",
        name="Amazon Seller Central",
        category="marketplace",
        region="global",
        integration="csv",
        auth="csv",
        summary="Amazon's SP-API needs an approved developer profile and a signed "
                "agreement, which a student project cannot honestly claim to hold.",
        pulls=("All-orders report", "ASIN and title", "Quantity ordered"),
        csv_route="Seller Central → Reports → Fulfilment → All Orders → request the "
                  "date range → Download.",
        docs_url="https://developer-docs.amazon.com/sp-api/",
        mark="Az",
        accent="#FF9900",
    ),
    ProviderSpec(
        key="flipkart-seller",
        name="Flipkart Seller Hub",
        category="marketplace",
        region="india",
        integration="csv",
        auth="csv",
        summary="Flipkart's Seller APIs are granted per seller account on request, so "
                "there is no shared app to authorise against.",
        pulls=("Order items", "Product titles", "Quantities"),
        csv_route="Seller Hub → Reports & Recommendations → Sales Report → "
                  "choose the period → Download.",
        docs_url="https://seller.flipkart.com/api-docs/",
        mark="Fk",
        accent="#2874F0",
    ),
    ProviderSpec(
        key="csv",
        name="CSV or Excel file",
        category="file",
        region="global",
        integration="csv",
        auth="csv",
        summary="Any file with a date, a product name and a quantity works. Column "
                "names are matched flexibly, so most exports load unchanged.",
        pulls=("Whatever your file contains",),
        csv_route="Drag the file onto the dashboard, or use Upload on the forecast page.",
        mark="··",
        accent="#475569",
    ),
)

BY_KEY = {provider.key: provider for provider in PROVIDERS}


def get(key: str) -> ProviderSpec | None:
    return BY_KEY.get(key)


def live_keys() -> list[str]:
    return [p.key for p in PROVIDERS if p.integration == "live"]
