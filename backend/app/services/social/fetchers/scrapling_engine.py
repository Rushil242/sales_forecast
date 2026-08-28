"""Scrapling-backed fetch layer for the open-web social connectors.

Why Scrapling rather than plain httpx
-------------------------------------
Most large sites no longer decide whether you are a bot from your user-agent; they
look at the TLS and HTTP/2 fingerprint of the connection itself. A stock Python
client is identifiable before it has sent a single header, which is why a
hand-rolled request to YouTube returns a consent wall while a browser returns
results. Scrapling's static ``Fetcher`` is built on curl_cffi and impersonates a
real browser's TLS fingerprint, and it ships a proper HTML/JSON parser on top.

Three engines, in increasing cost
---------------------------------
``http``     Scrapling's ``Fetcher``: TLS-impersonating, fast, no browser needed.
             This is what the shipped connectors use.
``browser``  ``DynamicFetcher``/``StealthyFetcher``: a real headless browser, for
             pages that render their content in JavaScript. It needs browser
             binaries installed (``scrapling install``), so it is *reported as
             unavailable* rather than silently skipped when they are absent.
``none``     Scrapling is not installed at all. Connectors that need it report
             themselves unavailable and the rest of the pipeline carries on.

Conduct
-------
This is a low-volume academic harvester, not a scraper farm. Every request is
throttled per domain, results are cached by the existing social snapshot TTL, and
the whole layer can be switched off with ``RETAILIQ_SCRAPING_ENABLED=false``. No
site is fetched more than a handful of times per analysis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit

LOG = logging.getLogger(__name__)

# Minimum seconds between two requests to the same host, applied globally.
DOMAIN_INTERVAL = 1.2

_domain_locks: dict[str, asyncio.Lock] = {}
_last_request: dict[str, float] = {}


@dataclass
class FetchOutcome:
    """The result of one fetch, including *why* it failed when it did."""

    ok: bool
    url: str
    engine: str            # http | browser | none
    status: int | None = None
    text: str = ""
    reason: str = ""
    cookies: dict[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    # JSON bodies of XHRs the page itself made, when `capture_xhr` was requested.
    # This is how we read endpoints that refuse a direct call but answer the site's
    # own front end -- the browser performs the request, we read the response.
    captured: list[object] = field(default_factory=list)

    def json(self) -> object | None:
        import json

        try:
            return json.loads(self.text)
        except Exception:
            return None


@lru_cache(maxsize=1)
def scrapling_available() -> bool:
    try:
        import scrapling.fetchers  # noqa: F401
    except Exception as exc:  # pragma: no cover - depends on the install
        LOG.info("Scrapling is not importable: %s", exc)
        return False
    return True


# The browser engine's real state is only knowable by launching it. A path check
# is not enough: patchright pins one Chromium revision, and a cache holding a
# *different* revision looks identical on disk while failing at launch -- which is
# exactly what happened here. So the result is recorded from actual use.
_browser_state: tuple[bool, str] | None = None


def browser_available() -> tuple[bool, str]:
    """What we know about the browser engine, and how we know it.

    Returns ``(usable, reason)``. Before any dynamic fetch has been attempted this
    reports "not yet exercised" rather than guessing, because guessing was wrong.
    """
    if not scrapling_available():
        return False, "Scrapling is not installed."
    if _browser_state is None:
        return False, "Not yet exercised in this process."
    return _browser_state


def _record_browser_state(usable: bool, reason: str = "") -> None:
    global _browser_state
    _browser_state = (usable, reason)


def _browser_hint(error: str) -> str:
    """Turn Playwright's multi-line launch failure into one actionable sentence."""
    if "Executable doesn't exist" in error or "playwright install" in error:
        return (
            "No usable browser binary. Install one into this virtualenv with "
            "`.venv/bin/patchright install chromium` (~150 MB), then retry."
        )
    return error.strip().splitlines()[0][:200]


def engine_status() -> dict[str, object]:
    """Reported on the connector inventory so the UI can state what is possible."""
    usable, reason = browser_available()
    return {
        "scrapling": scrapling_available(),
        "http_engine": scrapling_available(),
        "browser_engine": usable,
        "browser_probed": _browser_state is not None,
        "browser_reason": reason,
    }


async def _throttle(host: str) -> None:
    lock = _domain_locks.setdefault(host, asyncio.Lock())
    async with lock:
        elapsed = time.monotonic() - _last_request.get(host, 0.0)
        if elapsed < DOMAIN_INTERVAL:
            await asyncio.sleep(DOMAIN_INTERVAL - elapsed)
        _last_request[host] = time.monotonic()


def _fetch_sync(
    url: str, headers: dict[str, str] | None, cookies: dict[str, str] | None,
    timeout: float, dynamic: bool, capture_xhr: str | None = None,
    scroll: int = 0, wait_selector: str | None = None,
) -> tuple[int, str, dict[str, str], list[object]]:
    from scrapling.fetchers import DynamicFetcher, Fetcher

    if dynamic:
        def act(page):
            # Infinite-scroll grids only request the next batch once you reach the
            # bottom, so a page that is never scrolled reports far less than it has.
            for _ in range(scroll):
                page.mouse.wheel(0, 2200)
                page.wait_for_timeout(2500)
            if not scroll:
                page.wait_for_timeout(2500)
            return page

        options: dict[str, object] = {
            "timeout": int(timeout * 1000),
            "network_idle": True,
            "headless": True,
            "page_action": act,
        }
        if capture_xhr:
            options["capture_xhr"] = capture_xhr
        if wait_selector:
            options["wait_selector"] = wait_selector
            options["wait_selector_state"] = "attached"

        response = DynamicFetcher.fetch(url, **options)
        payloads: list[object] = []
        for record in getattr(response, "captured_xhr", None) or []:
            reader = getattr(record, "json", None)
            try:
                payloads.append(reader() if callable(reader) else reader)
            except Exception:  # a non-JSON response is simply not interesting here
                continue
        return (response.status, response.html_content,
                _cookie_map(response.cookies), payloads)
    else:
        response = Fetcher.get(
            url,
            timeout=timeout,
            stealthy_headers=True,
            follow_redirects=True,
            headers=headers or {},
            cookies=cookies or {},
            retries=1,
        )
    return response.status, response.html_content, _cookie_map(response.cookies), []


def _cookie_map(cookies: object) -> dict[str, str]:
    """Normalise the two cookie shapes the fetchers return.

    The static fetcher hands back a mapping; the browser hands back Playwright's
    list of cookie objects. Calling ``dict()`` on the latter raises an error that
    names neither cookies nor the browser, which cost a while to place.
    """
    if not cookies:
        return {}
    if isinstance(cookies, dict):
        return {str(k): str(v) for k, v in cookies.items()}
    jar: dict[str, str] = {}
    for cookie in cookies:
        if isinstance(cookie, dict) and "name" in cookie:
            jar[str(cookie["name"])] = str(cookie.get("value", ""))
    return jar


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    timeout: float = 25.0,
    dynamic: bool = False,
    capture_xhr: str | None = None,
    scroll: int = 0,
    wait_selector: str | None = None,
) -> FetchOutcome:
    """Fetch one URL, returning an outcome that always explains itself."""
    from app.config import get_settings

    settings = get_settings()
    if not settings.scraping_enabled:
        return FetchOutcome(
            ok=False, url=url, engine="none",
            reason="Web scraping is disabled (RETAILIQ_SCRAPING_ENABLED=false).",
        )
    if not scrapling_available():
        return FetchOutcome(
            ok=False, url=url, engine="none",
            reason="Scrapling is not installed. Run pip install 'scrapling[fetchers]'.",
        )
    host = urlsplit(url).netloc
    await _throttle(host)

    started = time.perf_counter()
    try:
        # Scrapling's fetchers are synchronous; a thread keeps the event loop free
        # so the other connectors continue harvesting in parallel.
        status, text, jar, captured = await asyncio.to_thread(
            _fetch_sync, url, headers, cookies, timeout, dynamic,
            capture_xhr, scroll, wait_selector,
        )
    except Exception as exc:
        reason = _browser_hint(str(exc)) if dynamic else f"{type(exc).__name__}: {exc}"[:200]
        if dynamic:
            _record_browser_state(False, reason)
        return FetchOutcome(
            ok=False, url=url, engine="browser" if dynamic else "http",
            reason=reason,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    engine = "browser" if dynamic else "http"
    if dynamic:
        _record_browser_state(True)

    # DuckDuckGo answers a rate-limited client with 202 and an "anomaly" notice
    # rather than 429. Read literally that is a success with no results, which is
    # how a throttled harvest ends up reported as "nobody is talking about this".
    if status == 202 and "anomaly" in text.lower():
        return FetchOutcome(
            ok=False, url=url, engine=engine, status=status, cookies=jar,
            elapsed_ms=elapsed_ms,
            reason="Rate-limited by the search endpoint (HTTP 202, anomaly notice). "
                   "This clears on its own after a few minutes.",
        )

    if status >= 400:
        return FetchOutcome(
            ok=False, url=url, engine=engine, status=status, cookies=jar,
            elapsed_ms=elapsed_ms,
            reason=(
                f"HTTP {status}. "
                + ("The site is blocking automated requests from this network."
                   if status in (401, 403, 429) else "The page could not be fetched.")
            ),
        )

    return FetchOutcome(
        ok=True, url=url, engine=engine, status=status, text=text,
        cookies=jar, elapsed_ms=elapsed_ms, captured=captured,
    )
