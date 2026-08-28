# RetailIQ — Agentic Retail Demand Intelligence

Zero-shot time-series foundation-model forecasting, fused with an agentic social
sentiment pipeline, served as a full-stack web application.

**Stack:** FastAPI · Amazon Chronos-Bolt · Nixtla statsforecast · SQLAlchemy ·
React 18 · Vite · Tailwind CSS · Recharts

---

## What this system does

1. **Forecasts demand** for any product in a transactional CSV using
   [Amazon Chronos-Bolt](https://github.com/amazon-science/chronos-forecasting),
   a time-series foundation model that predicts a previously-unseen series with
   no fitting step.
2. **Measures its own accuracy** on every request, backtesting the foundation
   model against AutoARIMA, AutoETS, Theta and seasonal-naive baselines over
   rolling origins, and returns MASE / RMSE / sMAPE / interval-coverage.
3. **Harvests real social signal** from public sources, filters noise, scores
   sentiment with a transformer, and converts it into a daily index in [−1, 1].
4. **Fuses sentiment into the forecast** through an elasticity calibrated
   against the product's own residual history — reporting whether that
   elasticity was measured or assumed.

---

## Design commitments

This rebuild replaced an earlier version whose outputs were largely simulated.
Four commitments govern the current system, each enforced by tests.

| Commitment | How it is enforced |
|---|---|
| **No synthetic history.** A series too short to forecast is refused, not padded. | `POST /forecast` returns `422 insufficient_data`. See `tests/test_series.py::test_short_series_is_refused_not_padded`. |
| **No injected seasonality.** Weekly patterns are whatever the data contains. | Weekend uplift is *measured* from history; if there is no effect, the card says so. `tests/test_series.py::test_weekend_uplift_is_measured_not_assumed`. |
| **No fabricated precision.** Intervals a model cannot produce are `null`. | Chronos-Bolt's heads are trained on quantiles 0.1–0.9, so `lower_95`/`upper_95` are omitted rather than clamped. |
| **No unattributed numbers.** Every social figure carries its provenance. | Responses report `provenance` (`live`/`cache`/`fixture`/`none`) and a per-connector status. |

The un-fused base forecast is returned alongside every adjusted point
(`base_units` vs `predicted_units`), so sentiment's contribution is always
auditable rather than baked invisibly into a single number.

---

## Quick start

Requirements: Python 3.11+, Node 18+, ~1 GB disk for model weights.

```bash
git clone <repo> && cd sales_forecast1
```

**Backend**

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev,trends]"
```

```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**Frontend** (separate terminal)

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:5173>. API docs at <http://localhost:8000/docs>.

The first forecast downloads Chronos-Bolt (~200 MB) and the first social query
downloads the sentiment model (~500 MB). Both are cached afterwards.

### Docker

```bash
docker compose up --build
```

Frontend on <http://localhost:8080>, API on <http://localhost:8000>. Model
weights persist in a named volume, so restarts do not re-download.

---

## The dataset

`data/retail_transactions.csv` — **real** transactions from
[Online Retail II (UCI)](https://doi.org/10.24432/C5CG6D): a UK-based online
giftware retailer, 2009-12-01 to 2011-12-09, curated to the 30 products with the
densest daily coverage.

| | |
|---|---|
| Rows | 63,609 |
| Products | 30 (519–602 selling days each) |
| Span | 739 calendar days |
| Regions | 38 countries |

Rebuild or extend it with:

```bash
cd backend && python -m scripts.build_dataset --out ../data --top-products 30
```

The script documents every cleaning rule and every derived column.
`Product Category` and `Color` are derived from real product-description text;
`Payment Method` does not exist in the source and is **not** emitted, because
inventing it would be fabrication. The ingestion layer treats it as optional
precisely so real-world files like this one are accepted.

**Why not the original Zara sample?** `data/Zara_Mens_Sales_Data.csv` is retained
for schema testing, but it spans only **15 days** (2024-01-01 to 2024-01-15).
No honest 30-day forecast can be produced from 15 daily observations, and its
daily totals run 85–95 units — a coefficient of variation of ~5.7%, i.e. almost
no weekly pattern at all. Requesting a forecast for it returns
`422 insufficient_data`, which is the correct answer.

---

## Measured results

Rolling-origin backtest, 5 non-overlapping 30-day windows, on the bundled
dataset. Lower is better; **MASE below 1.0 beats a seasonal-naive forecast**.

**White Hanging Heart T-Light Holder** (738 days)

| Model | MASE | RMSE | sMAPE | 80% coverage |
|---|---|---|---|---|
| **chronos-bolt** | **0.560** | 130.8 | 80.2% | **0.81** |
| theta | 0.585 | 126.9 | 76.8% | 0.97 |
| auto-ets | 0.598 | 126.9 | 73.0% | 0.96 |
| auto-arima | 0.631 | 134.9 | 85.9% | 0.95 |
| seasonal-naive | 0.948 | 212.2 | 92.8% | 0.95 |

**Jumbo Storage Bag Suki** (739 days)

| Model | MASE | RMSE | 80% coverage |
|---|---|---|---|
| **chronos-bolt** | **0.732** | 50.0 | **0.75** |
| auto-ets | 0.766 | 46.7 | 0.85 |
| auto-arima | 0.897 | 50.2 | 0.85 |
| theta | 0.912 | 49.5 | 0.88 |
| seasonal-naive | 1.250 | 76.6 | 0.84 |

Chronos-Bolt wins on MASE for both products (**−38.4%** and **−34.7%** RMSE
against seasonal-naive) and its intervals are by far the best calibrated: 0.81
and 0.75 against a nominal 0.80, where the statistical models sit at 0.95–0.97
— technically "safe" but too wide to inform a stocking decision.

Qualitatively, Chronos forecasts **0.0 units for every Saturday** on this
retailer — it recovered the weekend-closure pattern zero-shot, with no
seasonality supplied.

Reproduce with any product via the dashboard, or:

```bash
curl -X POST localhost:8000/api/v1/forecast -H 'Content-Type: application/json' -d '{"dataset":"online-retail-ii","product_name":"Jumbo Storage Bag Suki","horizon_days":30}'
```

---

## Data connectors

Retailers do not keep their sales in a CSV; they keep them in Shopify, Zoho,
Razorpay or Tally. The connect gallery lists eleven platforms, and it holds two
rules that are worth being explicit about because they are what makes the page
trustworthy:

**No logo produces data it did not fetch.** Shopify and Zoho are real OAuth
integrations against real APIs. Every other tile states plainly that the route is
a CSV export, and gives the exact menu path inside that product. There is no
third state where a logo returns invented orders.

**Missing setup is stated, not discovered on click.** A provider we have built
but whose API keys are absent shows exactly which environment variables are
missing, and the redirect URL to register, before the user commits to anything.

| Provider | Route | Why |
|---|---|---|
| **Shopify** | Real OAuth 2.0 + GraphQL Admin API | Publishes a public OAuth app; free Partner dev stores |
| **Zoho Books / Inventory** | Real OAuth 2.0 with refresh | The accounting suite Indian SMBs actually run, and the only one of them with a public OAuth app |
| WooCommerce | CSV export | Self-hosted stores issue per-store API keys; there is no central app to authorise |
| Razorpay | CSV export | Payments carry amounts but usually no product lines |
| Unicommerce | CSV export | Its own export already merges Amazon, Flipkart and own-site orders |
| Tally Prime | CSV export | Runs on the shop's own machine with no cloud API at all |
| Vyapar, myBillBook | CSV export | No public API |
| Amazon Seller Central | CSV export | SP-API requires an approved developer profile and a signed agreement |
| Flipkart Seller Hub | CSV export | Seller APIs are granted per account on request |

A synced connection becomes an ordinary dataset. `connector:<id>` goes through
the identical ingestion, schema resolution and data-quality gate as an uploaded
file — live Shopify data with 20 days of history is refused exactly as a CSV with
20 days would be. That uniformity is tested, not assumed
(`tests/test_connectors.py`).

**Tokens are encrypted at rest** with Fernet, keyed from `RETAILIQ_SECRET_KEY`,
even though the system has no login. A Shopify token grants read access to a real
shop's orders, and SQLite files get copied to laptops and attached to bug
reports. If the key is unset the process says so and uses an ephemeral one, so
connections do not silently survive in a form nobody can decrypt.

### Two Shopify facts worth knowing before the demo

1. **`read_orders` only exposes the last 60 days.** Full history needs
   `read_all_orders`, which Shopify enables freely on development stores. The
   sync detects a clipped window and names the missing scope rather than
   returning a short series without comment.
2. **Imported orders must set `processedAt`.** `createdAt` is assigned by
   Shopify, so a backfilled year of history would otherwise collapse onto the day
   it was imported. The connector reads `processedAt` for this reason.

### Seeding a demo store

`scripts/seed_shopify.py` pushes the bundled UCI transactions into your own free
development store as real products and orders, so the demo can run the other way
round: click Connect, approve on Shopify's own consent screen, press Sync, and
the forecast is computed from data that just came back out of Shopify.

```bash
cd backend
python -m scripts.seed_shopify --shop my-store --token shpat_xxx --dry-run
python -m scripts.seed_shopify --shop my-store --token shpat_xxx
```

---

## MCP server — the Phase 2 substrate

Phase 2 is an agentic chatbot with sub-agents routed by intent. Those agents need
a tool surface, and the worst way to build one is to have them make HTTP calls
back into our own API and re-parse their own JSON. So the tool surface is defined
once, in `app/mcp_server.py`, in terms of the service layer — and the chatbot and
any external MCP client use the same one.

It is also useful today on its own: with it registered, Claude can query the real
data directly.

```bash
claude mcp add retailiq -- /absolute/path/to/backend/.venv/bin/retailiq-mcp
```

| Tool | Returns |
|---|---|
| `list_datasets` | Bundled samples, uploads, and synced connections |
| `list_products` | Products with history length and data-quality grade |
| `query_sales` | Observed daily units for one product, no forecast |
| `get_forecast` | Forecast plus its rolling-origin backtest |
| `explain_forecast` | The plain-English owner brief and its measured drivers |
| `run_social_agent` | Social analysis with per-source provenance |
| `list_forecasting_models` | Models available and which accept covariates |

**The agent surface is not a softer door.** Every tool calls the same service
functions the HTTP API calls, so a 15-day series is refused through MCP exactly
as it is through the dashboard, `lower_95` is still null where the model cannot
support it, and social results still carry their provenance. This is tested
directly (`tests/test_mcp.py::test_the_refusal_survives_the_agent_path`) — it is
the reason business logic lives in the service layer and never in route handlers.

---

## The social intelligence agent

Pipeline: **collect → filter → score → aggregate → interpret**.

### Connectors

| Connector | Type | Auth | Status (measured 2026-08-26) |
|---|---|---|---|
| **News** (Google News RSS) | documents | none | ✅ Working. India edition (`gl=IN`); no engagement metric |
| **Hacker News** (Algolia) | documents | none | ✅ Working. Real points and comments; technology-skewed audience |
| **YouTube** | documents | none | ✅ Working via Scrapling. Reviews, hauls, unboxings — where opinion about physical retail products actually lives |
| **Blogs & reviews** | documents | none | ✅ Working via Scrapling. Discovered through DuckDuckGo, then each page is opened and its own publication date read |
| **Google Trends** (pytrends) | signal | none | ✅ Working. Daily search interest; excluded from sentiment averages |
| **Reddit** | documents | **OAuth required** | ⚠️ HTTP 403 anonymously; free credentials enable it |
| **Pinterest** | documents | none | ❌ Blocked. See below |
| **Instagram** | documents | **Apify token** | ⚠️ No anonymous endpoint exists; runs via Apify |
| **X** | documents | **Apify token** | ⚠️ Same |

Connectors run concurrently and fail independently. Every one that cannot run
says why, in the response body.

**Why some of these are blocked, stated precisely.** These are measurements, not
excuses, and each is reproducible with `pytest tests/test_scraping_live.py -m network`:

- **Pinterest** — the public search page answers `200`, but its embedded
  `__PWS_DATA__` payload contains no pins; the grid is filled by a later XHR.
  That XHR (`/resource/BaseSearchResource/get/`) answers **403 Invalid Resource
  Request** anonymously — including when the request carries the `csrftoken` and
  `_pinterest_sess` cookies fetched from the search page a moment earlier, plus
  the `X-CSRFToken` and `X-Requested-With` headers the site's own JavaScript
  sends. The rendered-page fallback is implemented and works as soon as a browser
  binary is installed (`.venv/bin/patchright install chromium`).
- **Instagram and X** — neither has an anonymous search endpoint at all. This is
  not a bot-detection problem that a better TLS fingerprint solves; there is
  nothing to call. Scraping them would mean driving a logged-in account, which
  breaks their terms. Apify runs those scrapers under its own terms and its free
  monthly credit covers this project's volume, so that is the honest route.
- **Reddit** — withdrew anonymous JSON access in 2023. Free credentials from
  <https://www.reddit.com/prefs/apps> restore it.

**Why Scrapling rather than plain httpx.** Large sites no longer decide whether
you are a bot from your user-agent; they read the TLS and HTTP/2 fingerprint of
the connection itself. A stock Python client is identifiable before it sends a
header. Scrapling's static `Fetcher` is built on curl_cffi and impersonates a real
browser's handshake. This is a low-volume academic harvester — every request is
throttled per domain, results are cached, and the whole layer switches off with
`RETAILIQ_SCRAPING_ENABLED=false`.

### Noise filtering

Explicit, individually auditable rules: promotional/affiliate spam, off-topic
documents, bot-pattern authors, syndication duplicates, and too-short content.
Every rejected document keeps a `filter_reason`, and both pre- and post-filter
counts are reported.

### Sentiment model — and why it is not FinBERT

The literature review cites FinBERT (Araci, 2019), so FinBERT was implemented and
measured first. It performs poorly on consumer text because it was fine-tuned on
*financial* communications, where "positive" means bullish, not pleased.

On the labelled set in `tests/test_sentiment.py`:

| Model | Agreement |
|---|---|
| `cardiffnlp/twitter-roberta-base-sentiment-latest` (default) | **8/8** |
| `ProsusAI/finbert` | 6/8 |

FinBERT scores *"Not good at all, would not recommend to anyone"* at **−0.00**
and labels it neutral; it scores *"everyone is obsessed with it"* at −0.03. The
default scores those −0.91 and +0.65.

Reproduce:

```bash
cd backend && .venv/bin/python -m scripts.compare_sentiment_models
```

Polarity is `P(positive) − P(negative)`, not the argmax label, so intensity is
preserved. If the transformer cannot load, a lexicon fallback keeps the service
alive and the response says so — the two are not equivalent.

### Aggregation

Aggregates are **engagement-weighted** using `log1p(engagement)`, so a widely-seen
post counts for more than an unseen one without a single viral post defining the
index. Trend percentages are **suppressed** for sources that cap results and
return newest-first (tag timelines in particular), because the earlier half of the
window is under-sampled and any comparison would overstate growth.

### Offline replay

```bash
cd backend && python -m scripts.record_fixture "Christmas decorations"
```

Records a genuine harvest to `data/fixtures/`. If live sources later return
nothing, the agent replays it and labels the response `provenance="fixture"`
with the recording date, rather than substituting invented data.

---

## Sentiment–forecast fusion

Chronos-Bolt is univariate and takes no covariates, so sentiment cannot be fed to
it directly. Instead of asserting a relationship, the system measures whether one
exists in the product's own history:

1. Compute each day's sales relative to a trailing local level — this strips the
   trend and weekly cycle the base model already captures.
2. Regress that deviation on the sentiment index at lags 0–7 days (Duan et al.
   2021 put the social-to-sales lead at 3–7 days).
3. Keep the best-fitting lag, accepted only above an R² floor. The slope is the
   **elasticity**.
4. Apply it to the horizon, bounded by `fusion_max_adjustment` (default ±25%).

The response reports which happened:

- **`calibrated`** — an elasticity was fitted, with its R², lag and overlap.
- **`prior`** — insufficient overlap, so a small bounded prior was used. Stated
  explicitly as *"an assumption, not a measurement"* in both API and UI.
- **`unavailable`** — no sentiment; the forecast rests on history alone.

**A known and honest limitation:** the bundled dataset ends in 2011, so it can
never overlap a social harvest from today. Fusion on it will always report
`prior`. The `calibrated` path is exercised by `tests/test_fusion.py`, which
plants a known elasticity at a known lag and confirms both are recovered. Real
calibration requires sales and social data covering the same period.

---

## API

Base path `/api/v1`. Interactive docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/ready` | Readiness with subsystem detail |
| `GET` | `/api/v1/models` | Available forecasters and availability |
| `GET` | `/api/v1/datasets` | Bundled datasets and synced connections |
| `GET` | `/api/v1/datasets/{id}` | Dataset detail and product list |
| `POST` | `/api/v1/datasets/upload` | Upload a CSV, returns a reusable token |
| `POST` | `/api/v1/forecast` | Generate a forecast |
| `POST` | `/api/v1/forecast/upload` | Upload and forecast in one call |
| `GET` | `/api/v1/social` | Social analysis for a product |
| `GET` | `/api/v1/social/connectors` | Social connector inventory and config state |
| `GET` | `/api/v1/connectors` | Connect gallery: every platform and its real state |
| `GET` | `/api/v1/connect/{provider}/start` | 302 to the platform's own consent screen |
| `GET` | `/api/v1/connect/{provider}/callback` | OAuth callback |
| `POST` | `/api/v1/connectors/{id}/sync` | Pull order history from a connection |
| `DELETE` | `/api/v1/connectors/{id}` | Remove a connection and its synced data |
| `GET` | `/api/v1/runs` | Audit trail of past forecasts |

Errors are structured with a stable machine-readable `code`, so clients branch on
the failure kind rather than matching prose:

```json
{"error": {"code": "insufficient_data",
           "message": "'Cargo Shorts' has only 15 days of history...",
           "details": {"observations": 15, "required": 30},
           "request_id": "f2dcc6bfc6c1"}}
```

Every response carries `X-Request-ID` and `X-Process-Time-Ms`.

### Flexible input schema

Only three columns are required — a date, a product identifier and a quantity —
resolved through a case- and punctuation-insensitive alias table. `Units Sold`,
`units_sold`, `Quantity`, `qty` and `y` all resolve to the same field. Everything
else is an optional enrichment. This is a deliberate fix: the earlier version
demanded ten exact column names and rejected any other file.

---

## Tests

```bash
cd backend && .venv/bin/python -m pytest -m "not slow"
```

93 tests covering ingestion and schema resolution, series construction and the
refusal path, the forecaster contract, accuracy metrics, backtest window
planning, fusion calibration and bounds, noise filtering, aggregation, and the
API contract end-to-end.

```bash
.venv/bin/python -m pytest -m slow
```

Additionally downloads models and verifies sentiment quality against the
labelled set. `-m network` marks tests needing outbound internet.

---

## Project layout

```
sales_forecast1/
├── backend/
│   ├── app/
│   │   ├── api/routes/       forecast, social, health endpoints
│   │   ├── core/             errors, structured logging
│   │   ├── db/               SQLAlchemy models and session
│   │   ├── schemas/          pydantic response contracts
│   │   ├── mcp_server.py     the service layer exposed as MCP agent tools
│   │   └── services/
│   │       ├── connectors/   shopify, zoho, registry, token encryption, sync
│   │       ├── enrichment/   weather, holidays, calendar, sentiment, geo, builder
│   │       ├── forecasting/  chronos2, chronos, statistical, backtest, metrics,
│   │       │                 fusion, covariate_selection
│   │       ├── narrative/    Gemini client, schemas, number-provenance guard
│   │       ├── social/       connectors, fetchers/, noise filter, sentiment, agent
│   │       ├── ingestion.py  CSV parsing and schema resolution
│   │       ├── series.py     daily series and data-quality assessment
│   │       └── insights.py   derived business insights
│   ├── scripts/              build_dataset, seed_shopify, record_fixture,
│   │                         compare_sentiment_models
│   └── tests/
├── frontend/src/
│   ├── components/           charts, UI primitives, OwnerBrief, CovariatePanel
│   ├── pages/                Dashboard, Connect, SocialIntelligence
│   └── lib/                  API client and formatting
└── data/                     curated dataset, fixtures, connector syncs, SQLite
```

---

## Known limitations

1. **Fusion cannot calibrate on the bundled data.** Sales end in 2011; social
   data is current. Reported as `prior` mode, never disguised.
2. **Niche SKUs have little social presence.** A query like *"White Hanging
   Heart T-Light Holder"* returns few documents. The system reports the thin
   evidence rather than padding it — informative, not a defect.
3. **Reddit, Instagram and X require credentials.** All free, but a setup step.
4. **Pinterest is blocked without a browser binary.** Implemented and measured;
   see the connector table for the exact HTTP behaviour.
5. **Hacker News skews technical.** Strong for brand and retailer discussion,
   weak for individual homeware SKUs.
6. **YouTube dates are approximate.** Search results carry "3 days ago", never a
   timestamp. Every such document is flagged `date_is_approximate`.
7. **Zoho's first sync is slow and bounded.** Zoho serves invoice line items one
   invoice at a time, so the sync is capped and reports when it hits the cap.
8. **Models are re-loaded per process, not shared.** Fine for single-instance
   deployment; a multi-worker deployment would want a shared model server.
9. **Intermittent demand** (>50% zero days) is flagged but still modelled
   continuously. Croston or TSB would be the correct family.

---

## Citations

- Ansari et al. (2024). *Chronos: Learning the Language of Time Series.* arXiv:2403.07815
- Hyndman & Khandakar (2008). *Automatic Time Series Forecasting.* JSS 27(3)
- Hyndman & Koehler (2006). *Another look at measures of forecast accuracy.* IJF 22(4)
- Makridakis et al. (2018). *The M4 Competition.* IJF 34(4)
- Araci (2019). *FinBERT.* arXiv:1908.10063
- Barbieri et al. (2020). *TweetEval.* Findings of EMNLP 2020
- Chen (2019). *Online Retail II* [Dataset]. UCI ML Repository. doi:10.24432/C5CG6D
