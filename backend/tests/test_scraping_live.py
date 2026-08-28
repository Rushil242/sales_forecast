"""Live measurements of what each open-web source actually returns.

Marked ``network`` so it never runs in the ordinary suite. Run it when you want
the current, real answer rather than the one recorded in a docstring:

    pytest tests/test_scraping_live.py -m network -v -s

This file is deliberately written as *measurement*, not as pass/fail assertion of
third-party behaviour. Pinterest blocking us is not a bug in this code, and a test
that fails when Pinterest changes its mind would just get muted. What these do
assert is the thing we control: that a blocked source produces a specific,
actionable reason and never fabricates documents.
"""

from __future__ import annotations

import pytest

from app.services.social.pinterest import PinterestConnector
from app.services.social.web import WebConnector
from app.services.social.youtube import YouTubeConnector

QUERY = "cake stand"

pytestmark = [pytest.mark.network, pytest.mark.slow]


@pytest.mark.asyncio
async def test_youtube_returns_real_dated_documents():
    documents = await YouTubeConnector().fetch(QUERY, 365, 10)
    print(f"\nYouTube: {len(documents)} documents in a 365-day window")
    for document in documents[:5]:
        print(f"  {document.published_at.date()}  {document.engagement:>10,.0f} views  "
              f"{document.title[:50]}")

    assert documents, "YouTube returned nothing; the search layout may have changed."
    assert all(d.url and d.url.startswith("https://www.youtube.com/watch") for d in documents)
    assert all(d.extra.get("date_is_approximate") for d in documents)


@pytest.mark.asyncio
async def test_blog_connector_only_keeps_pages_it_could_date():
    documents = await WebConnector().fetch(QUERY, 3650, 10)
    print(f"\nBlogs & reviews: {len(documents)} dated documents")
    for document in documents:
        print(f"  {document.published_at.date()}  {document.author}")

    # The contract is not "finds articles" -- search results vary by the hour.
    # It is that everything returned carries a date read off the page itself.
    for document in documents:
        assert document.extra.get("date_source") == "page metadata"
        assert document.published_at is not None


@pytest.mark.asyncio
async def test_pinterest_is_blocked_and_says_exactly_why():
    """Measured 2026-08-26: 403 'Invalid Resource Request' even with session cookies."""
    with pytest.raises(RuntimeError) as caught:
        await PinterestConnector().fetch(QUERY, 90, 10)

    message = str(caught.value)
    print(f"\nPinterest: {message}")
    # The point of the test: the failure is specific and actionable, and no
    # documents were invented to paper over it.
    assert "403" in message
    assert "browser" in message.lower()
