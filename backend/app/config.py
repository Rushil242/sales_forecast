"""Application configuration.

Every knob is settable through the environment or a ``.env`` file, so no
deployment ever needs a code change. See ``.env.example`` at the repo root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_prefix="RETAILIQ_",
        extra="ignore",
        case_sensitive=False,
    )

    # ── application ──────────────────────────────────────────────────────────
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_json: bool = False
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:3000", "http://127.0.0.1:3000",
        ]
    )

    # ── storage ──────────────────────────────────────────────────────────────
    data_dir: Path = REPO_ROOT / "data"
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'retailiq.db'}"
    max_upload_bytes: int = 64 * 1024 * 1024

    # ── forecasting ──────────────────────────────────────────────────────────
    chronos_enabled: bool = True
    chronos_model_id: str = "amazon/chronos-bolt-small"
    # Chronos-2 is the covariate-capable model and the default. Chronos-Bolt is
    # retained as the univariate comparison in the backtest.
    chronos2_enabled: bool = True
    chronos2_model_id: str = "amazon/chronos-2"
    default_model: str = "chronos-2"
    chronos_device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    chronos_context_length: int = 512
    forecast_default_horizon: int = 30
    forecast_max_horizon: int = 180
    # A series shorter than this cannot support an honest forecast; the API
    # refuses rather than padding with invented history.
    min_observations: int = 30
    # Below this, the response carries an explicit low-confidence warning.
    recommended_observations: int = 120

    # ── backtesting ──────────────────────────────────────────────────────────
    backtest_windows: int = 5
    backtest_max_windows: int = 12

    # ── enrichment (external covariates) ─────────────────────────────────────
    # Both sources are free and need no API key at all.
    enrichment_enabled: bool = True
    enrichment_weather_enabled: bool = True      # Open-Meteo
    enrichment_holidays_enabled: bool = True     # Nager.Date
    enrichment_timeout: float = 25.0
    # Leave-one-group-out attribution costs one extra forecast per group.
    attribution_enabled: bool = True

    # ── data connectors ──────────────────────────────────────────────────────
    # Encrypts stored OAuth tokens. Any long random string works; without it the
    # key is ephemeral and connections do not survive a restart.
    secret_key: str | None = None
    # Where the platform sends the browser back. Must exactly match the redirect
    # URI registered in the Shopify/Zoho app -- OAuth compares it byte for byte.
    public_base_url: str = "http://localhost:8000"
    # Where we bounce the user afterwards, i.e. the web app.
    app_base_url: str = "http://localhost:5173"
    connector_sync_days: int = 730
    connector_timeout: float = 40.0

    # Free to create at partners.shopify.com; a development store costs nothing.
    shopify_api_key: str | None = None
    shopify_api_secret: str | None = None
    shopify_scopes: str = "read_orders,read_products"
    shopify_api_version: str = "2025-01"

    # Free at api-console.zoho.in (or .com). Region matters: a token issued by
    # accounts.zoho.in is not valid against zohoapis.com.
    zoho_client_id: str | None = None
    zoho_client_secret: str | None = None
    zoho_region: Literal["in", "com", "eu", "au", "jp", "ca"] = "in"
    zoho_organization_id: str | None = None
    # Zoho serves invoice line items only one invoice at a time, so a first sync
    # is bounded rather than open-ended. Hitting the bound is reported, not hidden.
    zoho_max_invoices: int = 600

    # ── LLM narrative (Google AI Studio) ─────────────────────────────────────
    google_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # The social brief (headline + summary + findings + actions + evidence note) runs
    # longer than the forecast brief, and gemini-2.5-flash spends part of this budget
    # on thinking tokens. At 2048 the JSON came back truncated mid-string and the
    # guard correctly rejected it, so every brief silently fell back to the template.
    gemini_max_tokens: int = 8192
    gemini_timeout: float = 45.0
    narrative_enabled: bool = True

    # ── social intelligence ──────────────────────────────────────────────────
    social_enabled: bool = True
    social_lookback_days: int = 30
    social_cache_ttl_seconds: int = 6 * 3600
    social_max_documents: int = 400
    # Hard ceiling per source. Browser-backed sources are slow by nature, so this
    # is generous -- but a harvest that never returns is worse than a thin one.
    social_connector_timeout: float = 120.0
    social_request_timeout: float = 20.0
    # Google Trends region. Worldwide search interest is the wrong denominator for
    # an Indian retailer: "kurti" barely registers globally and looks like a dead
    # product. Set to "" for worldwide.
    trends_geo: str = "IN"
    # Connectors to attempt, in order. Unavailable ones are skipped and reported.
    # Ordered roughly by how reliably they return anything. Sources that are
    # currently blocked (pinterest) or need a key (reddit, instagram, x) are left
    # enabled on purpose: the response then states what was tried and why it
    # failed, which is more useful than a short list that looks clean.
    social_connectors: list[str] = Field(
        default=[
            "news", "hackernews", "youtube", "web",
            "trends", "reddit", "pinterest", "instagram", "x",
        ]
    )
    # Reddit withdrew anonymous access to its JSON endpoints, so this connector
    # needs free OAuth credentials from https://www.reddit.com/prefs/apps.
    # Without them it reports itself unavailable and the others carry on.
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "RetailIQ/1.0 (academic research project)"
    # India edition. Google News honours gl/ceid, so this is a real restriction
    # rather than a wording nudge -- it changes which outlets are searched.
    news_feeds: list[str] = Field(
        default=[
            "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en",
        ]
    )

    # ── open-web scraping (Scrapling) ────────────────────────────────────────
    # A low-volume academic harvester: every request is throttled per domain and
    # results are cached for social_cache_ttl_seconds. Set false to disable.
    scraping_enabled: bool = True
    scraping_timeout: float = 25.0
    # Apify runs the Instagram and X actors we cannot reach ourselves, because
    # both are behind a login wall no amount of stealth fixes. Free monthly credit.
    apify_token: str | None = None
    apify_instagram_actor: str = "apify~instagram-hashtag-scraper"
    apify_tweet_actor: str = "apidojo~tweet-scraper"
    apify_timeout: float = 120.0

    # ── sentiment ────────────────────────────────────────────────────────────
    # Default is the Twitter/X-domain RoBERTa rather than FinBERT. FinBERT is
    # fine-tuned on financial communications and mislabels ordinary consumer
    # opinion as neutral -- see tests/test_sentiment.py, which measures both on a
    # labelled set. Set RETAILIQ_SENTIMENT_MODEL_ID=ProsusAI/finbert to compare.
    sentiment_model_id: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    sentiment_batch_size: int = 32
    sentiment_max_length: int = 256

    # ── optional LLM narrative ───────────────────────────────────────────────
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 1200

    # ── fusion ───────────────────────────────────────────────────────────────
    fusion_enabled: bool = True
    # Literature (Duan et al. 2021) puts social signal lead time at 3-7 days.
    fusion_candidate_lags: list[int] = Field(default=[0, 1, 2, 3, 4, 5, 6, 7])
    # Minimum overlapping days before we trust a fitted elasticity instead of
    # falling back to a bounded prior.
    fusion_min_overlap_days: int = 45
    # Hard cap on how much sentiment may move a forecast, either direction.
    fusion_max_adjustment: float = 0.25
    fusion_prior_elasticity: float = 0.08

    @field_validator("cors_origins", "social_connectors", "news_feeds", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow comma-separated strings in env vars, e.g. RETAILIQ_CORS_ORIGINS=a,b."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("fusion_candidate_lags", mode="before")
    @classmethod
    def _split_int_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item) for item in value.split(",") if item.strip()]
        return value

    @property
    def has_llm(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_shopify(self) -> bool:
        return bool(self.shopify_api_key and self.shopify_api_secret)

    @property
    def has_zoho(self) -> bool:
        return bool(self.zoho_client_id and self.zoho_client_secret)

    @property
    def has_gemini(self) -> bool:
        return bool(self.google_api_key)

    @property
    def has_apify(self) -> bool:
        return bool(self.apify_token)

    @property
    def has_reddit_oauth(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)

    def resolve_device(self) -> str:
        """Pick a torch device, preferring Apple Silicon MPS then CUDA."""
        if self.chronos_device != "auto":
            return self.chronos_device
        try:
            import torch
        except ImportError:
            return "cpu"
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"


@lru_cache
def get_settings() -> Settings:
    return Settings()
