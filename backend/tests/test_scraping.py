"""Smoke tests for the Scrapling-backed connectors.

These run offline. Each connector is fed a recorded fragment of the real payload
shape and checked for the behaviour that matters -- chiefly that it drops what it
cannot date rather than stamping it with "now", which would put months-old
documents on this week's sentiment timeline.

The live behaviour of each source is measured in ``tests/test_scraping_live.py``
and marked ``network``, so it is available on demand without making the ordinary
suite depend on the internet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services.social.apify import InstagramConnector, XConnector
from app.services.social.fetchers import scrapling_engine
from app.services.social.fetchers.scrapling_engine import FetchOutcome
from app.services.social.web import _decode_result_url, _published_from_html
from app.services.social.youtube import YouTubeConnector


def _outcome(text: str) -> FetchOutcome:
    return FetchOutcome(ok=True, url="https://example.test", engine="http",
                        status=200, text=text)


# ── the engine reports why, always ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_scraping_can_be_switched_off_and_says_so(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("RETAILIQ_SCRAPING_ENABLED", "false")
    outcome = await scrapling_engine.fetch("https://example.com")
    get_settings.cache_clear()

    assert outcome.ok is False
    assert "disabled" in outcome.reason.lower()
    assert outcome.engine == "none"


def test_browser_state_is_unknown_until_it_is_exercised(monkeypatch):
    monkeypatch.setattr(scrapling_engine, "_browser_state", None)
    usable, reason = scrapling_engine.browser_available()
    assert usable is False
    # Crucially it does not claim the browser is broken -- only that we have not
    # looked. A path check claiming otherwise is what produced a wrong answer.
    assert "not yet exercised" in reason.lower()


def test_a_failed_browser_launch_becomes_one_actionable_sentence():
    hint = scrapling_engine._browser_hint(
        "Error: BrowserType.launch: Executable doesn't exist at /some/path\n"
        "╔══════╗\n║ Looks like Playwright was just installed ║\n"
    )
    assert "patchright install chromium" in hint
    assert "\n" not in hint


# ── YouTube ──────────────────────────────────────────────────────────────────
def _youtube_page(videos: list[dict]) -> str:
    payload = {"contents": {"items": [{"videoRenderer": v} for v in videos]}}
    return f"var ytInitialData = {json.dumps(payload)};</script>"


def _video(video_id: str, title: str, published: str, views: str) -> dict:
    return {
        "videoId": video_id,
        "title": {"runs": [{"text": title}]},
        "publishedTimeText": {"simpleText": published},
        "viewCountText": {"simpleText": views},
        "ownerText": {"runs": [{"text": "A Channel"}]},
    }


@pytest.mark.asyncio
async def test_youtube_parses_results_and_flags_approximate_dates(monkeypatch):
    page = _youtube_page([_video("abc123", "Cake stand review", "3 days ago", "8,692 views")])
    monkeypatch.setattr(
        "app.services.social.youtube.fetch",
        lambda *a, **k: _async(_outcome(page)),
    )
    documents = await YouTubeConnector().fetch("cake stand", 30, 10)

    assert len(documents) == 1
    document = documents[0]
    assert document.title == "Cake stand review"
    assert document.engagement == 8692
    assert document.url == "https://www.youtube.com/watch?v=abc123"
    # "3 days ago" is not a date, and the document says so all the way through.
    assert document.extra["date_is_approximate"] is True


@pytest.mark.asyncio
async def test_youtube_drops_results_outside_the_window(monkeypatch):
    page = _youtube_page([
        _video("recent", "Recent", "2 days ago", "10 views"),
        _video("old", "Old", "3 years ago", "10 views"),
        _video("undated", "Live now", "", "10 views"),
    ])
    monkeypatch.setattr(
        "app.services.social.youtube.fetch", lambda *a, **k: _async(_outcome(page))
    )
    documents = await YouTubeConnector().fetch("cake stand", 30, 10)
    assert [d.title for d in documents] == ["Recent"]


@pytest.mark.asyncio
async def test_youtube_layout_change_is_an_error_not_an_empty_result(monkeypatch):
    """A broken parser must never look like "nobody is talking about this"."""
    monkeypatch.setattr(
        "app.services.social.youtube.fetch",
        lambda *a, **k: _async(_outcome("<html>no payload here</html>")),
    )
    with pytest.raises(RuntimeError, match="ytInitialData"):
        await YouTubeConnector().fetch("cake stand", 30, 10)


# ── blogs and reviews ────────────────────────────────────────────────────────
def test_publication_date_is_read_from_the_page_itself():
    html = '<meta property="article:published_time" content="2025-03-14T10:00:00Z">'
    assert _published_from_html(html).date().isoformat() == "2025-03-14"

    ld = (
        '<script type="application/ld+json">'
        '{"@type":"Article","datePublished":"2024-11-02"}</script>'
    )
    assert _published_from_html(ld).date().isoformat() == "2024-11-02"


def test_a_page_with_no_date_yields_nothing_rather_than_today():
    assert _published_from_html("<html><body>No metadata at all</body></html>") is None


def test_duckduckgo_redirects_are_unwrapped():
    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Freview&rut=x"
    assert _decode_result_url(wrapped) == "https://example.com/review"
    assert _decode_result_url("https://direct.example/x") == "https://direct.example/x"


# ── Apify ────────────────────────────────────────────────────────────────────
def test_apify_sources_name_the_variable_they_need(monkeypatch):
    """When the token is absent the reason must name it, not just say 'unavailable'.

    Forced rather than assumed: a developer with RETAILIQ_APIFY_TOKEN set would
    otherwise see this pass for the wrong reason -- the connector being available.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("RETAILIQ_APIFY_TOKEN", raising=False)
    monkeypatch.setattr("app.config.Settings.has_apify", property(lambda self: False))
    try:
        for connector in (InstagramConnector(), XConnector()):
            assert "RETAILIQ_APIFY_TOKEN" in connector.unavailable_reason()
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_apify_refuses_rather_than_inventing_when_unconfigured(monkeypatch):
    """With no token it must refuse outright -- never quietly return nothing."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("app.config.Settings.has_apify", property(lambda self: False))
    try:
        with pytest.raises(PermissionError):
            await InstagramConnector().fetch("cake stand", 30, 10)
    finally:
        get_settings.cache_clear()


def test_x_documents_weight_reposts_above_likes():
    now = datetime.now(UTC).isoformat()
    document = XConnector().to_document({
        "createdAt": now, "text": "Lovely cake stand",
        "author": {"userName": "someone"},
        "likeCount": 10, "retweetCount": 5, "replyCount": 2,
    })
    assert document is not None
    assert document.engagement == 10 + 5 * 2.0 + 2 * 1.5


def test_undated_apify_items_are_dropped():
    assert XConnector().to_document({"text": "No timestamp here"}) is None
    assert InstagramConnector().to_document({"caption": "No timestamp"}) is None


def test_x_window_start_matches_the_lookback():
    payload = XConnector().build_input("cake stand", 30, 20)
    expected = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
    assert payload["start"] == expected


async def _async(value):
    return value


# ── cookie shapes ────────────────────────────────────────────────────────────
def test_browser_and_http_cookie_shapes_both_normalise():
    """The two fetchers disagree about what a cookie jar is.

    The static fetcher returns a mapping; the browser returns Playwright's list of
    cookie objects. Calling dict() on the latter raises an error mentioning
    neither cookies nor the browser, which is a genuinely confusing way to lose a
    working page.
    """
    from app.services.social.fetchers.scrapling_engine import _cookie_map

    assert _cookie_map({"csrftoken": "abc"}) == {"csrftoken": "abc"}
    assert _cookie_map([
        {"name": "csrftoken", "value": "abc", "domain": ".x.com", "path": "/",
         "expires": 1, "httpOnly": False, "secure": True, "sameSite": "Lax"},
    ]) == {"csrftoken": "abc"}
    assert _cookie_map(None) == {}


@pytest.mark.asyncio
async def test_a_rate_limited_search_is_not_reported_as_no_results(monkeypatch):
    """DuckDuckGo answers a throttled client with 202, not 429.

    Read literally that is "success, nothing found", which is how a throttled
    harvest gets reported as "nobody is talking about this product".
    """
    from app.services.social.fetchers import scrapling_engine

    def fake(url, headers, cookies, timeout, dynamic, capture_xhr=None,
             scroll=0, wait_selector=None):
        return 202, "<html>...anomaly detected in traffic...</html>", {}, []

    monkeypatch.setattr(scrapling_engine, "_fetch_sync", fake)
    monkeypatch.setattr(scrapling_engine, "scrapling_available", lambda: True)

    outcome = await scrapling_engine.fetch("https://html.duckduckgo.com/html/?q=x")
    assert outcome.ok is False
    assert "rate-limited" in outcome.reason.lower()
