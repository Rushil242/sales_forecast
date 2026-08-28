"""Noise filtering, aggregation and text normalisation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.social.aggregate import (
    build_platform_stats,
    build_timeline,
    build_trending_terms,
    label_for,
    sentiment_index_series,
    weighted_sentiment,
)
from app.services.social.base import RawDocument
from app.services.social.noise_filter import apply_filters
from app.services.social.textutil import hashtag_candidates, strip_html


def doc(title, *, source="Reddit", engagement=0.0, days_ago=1, score=None, author=None, text="",
        extra=None):
    document = RawDocument(
        source=source, title=title, text=text, author=author, engagement=engagement,
        published_at=datetime.now(UTC) - timedelta(days=days_ago),
        extra=extra or {},
    )
    if score is not None:
        document.sentiment_score = score
        document.sentiment_label = label_for(score)
    return document


# ── text normalisation ────────────────────────────────────────────────────────

def test_strip_html_removes_markup_and_urls():
    raw = '<p>Great <b>quality</b> mug!</p><a href="https://x.com/y">link</a>'
    assert strip_html(raw) == "Great quality mug! link"


def test_strip_html_unescapes_entities():
    assert strip_html("Tea &amp; coffee &lt;set&gt;") == "Tea & coffee <set>"


def test_strip_html_drops_script_content():
    assert "alert" not in strip_html("<script>alert('x')</script>Real text")


def test_hashtag_candidates_prefers_the_concatenated_form():
    assert hashtag_candidates("Cargo Shorts") == ["cargoshorts", "cargo", "shorts"]
    assert hashtag_candidates("Christmas") == ["christmas"]


# ── noise filter ──────────────────────────────────────────────────────────────

def test_rejects_promotional_content():
    documents = [
        doc("Buy now with discount code SAVE20 for these lovely mugs"),
        doc("These mugs are genuinely lovely, I use mine every single morning"),
    ]
    kept, reasons = apply_filters(documents, "mugs")

    assert len(kept) == 1
    assert reasons["promotional"] == 1


def test_rejects_off_topic_documents():
    documents = [
        doc("A long discussion about completely unrelated garden furniture prices"),
        doc("These ceramic mugs are the best purchase I have made all year"),
    ]
    kept, reasons = apply_filters(documents, "mugs")

    assert len(kept) == 1
    assert reasons["off_topic"] == 1


def test_deduplicates_syndicated_headlines():
    title = "Retailer reports strong demand for ceramic mugs this quarter"
    kept, reasons = apply_filters([doc(title), doc(title), doc(title)], "mugs")

    assert len(kept) == 1
    assert reasons["duplicate"] == 2


def test_rejects_bot_authors():
    documents = [
        doc("Lovely ceramic mugs available in many colours", author="deals_bot"),
        doc("Lovely ceramic mugs, a genuinely nice set for the price", author="real_person"),
    ]
    kept, reasons = apply_filters(documents, "mugs")

    assert len(kept) == 1
    assert reasons["bot_author"] == 1


def test_every_rejection_records_a_reason():
    documents = [doc("short"), doc("Buy now with promo code XX for mugs")]
    apply_filters(documents, "mugs")
    assert all(d.filter_reason for d in documents if not d.passed_filter)


def test_filter_keeps_everything_when_nothing_is_wrong():
    documents = [
        doc("These ceramic mugs hold heat beautifully and look lovely"),
        doc("Bought a second set of the ceramic mugs, very pleased with them"),
    ]
    kept, reasons = apply_filters(documents, "mugs")
    assert len(kept) == 2
    assert not reasons


# ── aggregation ───────────────────────────────────────────────────────────────

def test_sentiment_is_engagement_weighted():
    """A high-reach post must count for more than a low-reach one."""
    documents = [
        doc("Positive high reach", engagement=10_000, score=1.0),
        doc("Negative low reach", engagement=0, score=-1.0),
    ]
    weighted = weighted_sentiment(documents)
    simple = sum(d.sentiment_score for d in documents) / 2

    assert simple == pytest.approx(0.0)
    assert weighted > 0.4, "the widely-seen positive post should dominate"


def test_engagement_weighting_is_log_damped():
    """One viral post must shift the index without wholly defining it."""
    documents = [
        doc("Viral positive", engagement=1_000_000, score=1.0),
        *[doc(f"Negative {i}", engagement=5, score=-1.0) for i in range(20)],
    ]
    assert weighted_sentiment(documents) < 0, "twenty negatives should still outweigh one viral"


def test_timeline_distinguishes_silence_from_neutrality():
    documents = [doc("Nice mugs indeed", days_ago=1, score=0.5)]
    timeline = build_timeline(documents, lookback_days=7)

    assert len(timeline) == 7
    silent = [point for point in timeline if point.document_count == 0]
    assert silent, "days with no documents must still appear"
    assert all(point.sentiment_index == 0.0 for point in silent)

    active = [point for point in timeline if point.document_count > 0]
    assert len(active) == 1
    assert active[0].sentiment_index > 0


def test_trend_suppressed_when_source_truncates_results():
    """A recency-capped source must not report a spurious surge."""
    documents = [
        doc(f"Mastodon post {i}", source="Mastodon", days_ago=d, score=0.2,
            extra={"truncated": True})
        for i, d in enumerate([1, 2, 3, 4, 5, 20])
    ]
    stats = build_platform_stats(documents, lookback_days=30)

    assert stats[0].trend_pct is None
    assert "caps results" in stats[0].note


def test_trend_reported_when_window_is_covered():
    documents = [
        *[doc(f"Recent {i}", source="News", days_ago=2, score=0.1) for i in range(6)],
        *[doc(f"Older {i}", source="News", days_ago=25, score=0.1) for i in range(3)],
    ]
    stats = build_platform_stats(documents, lookback_days=30)

    assert stats[0].trend_pct == pytest.approx(100.0)


def test_trending_terms_exclude_the_query_and_stopwords():
    documents = [
        doc("The ceramic mugs are lovely and the glaze is beautiful", score=0.6),
        doc("Ceramic mugs with a lovely glaze, very pleased", score=0.5),
    ]
    terms = build_trending_terms(documents, "mugs")
    names = {term.term for term in terms}

    assert "mugs" not in names, "the query term is not a finding"
    assert "the" not in names and "and" not in names
    assert "lovely" in names or "glaze" in names


def test_trending_terms_exclude_markup_tokens():
    documents = [doc("href font color mugs are span div lovely", score=0.4)]
    names = {term.term for term in build_trending_terms(documents, "mugs")}
    assert not ({"href", "font", "color", "span", "div"} & names)


def test_sentiment_index_series_only_covers_observed_days():
    documents = [doc("A", days_ago=1, score=0.5), doc("B", days_ago=1, score=0.1),
                 doc("C", days_ago=5, score=-0.3)]
    index = sentiment_index_series(documents)

    assert len(index) == 2, "silent days must be absent, not zero-filled"
    assert all(-1 <= value <= 1 for value in index.values())


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.9, "positive"), (0.16, "positive"), (0.0, "neutral"),
        (-0.1, "neutral"), (-0.8, "negative"),
    ],
)
def test_label_thresholds(score, expected):
    assert label_for(score) == expected


# ── relevance: a weak query word must not carry the whole match ───────────────

def test_generic_query_word_does_not_admit_an_unrelated_document():
    """"Printed A-Line Kurti" was matching Japanese posts about the LINE app.

    Any-term matching let "line" -- a word that identifies nothing -- stand in for
    the product. The distinctive term is "kurti", and only that should qualify.
    """
    junk = doc(
        "「LINE VOOM」ついに左遷。間もなくクビ",
        source="Mastodon",
        text="「LINE VOOM」ついに左遷。間もなくクビ #jetstream_blog #Android",
    )
    real = doc(
        "Loving this printed kurti",
        source="Mastodon",
        text="Loving this printed kurti I picked up in Bangalore, so comfortable",
    )
    kept, reasons = apply_filters([junk, real], "Printed A-Line Kurti")

    assert [d.title for d in kept] == ["Loving this printed kurti"]
    assert junk.filter_reason == "off_topic"
    assert reasons["off_topic"] == 1


def test_url_slugs_do_not_count_as_relevance():
    """A link ending /line-voom-demoted/ is machine text, not something anyone said."""
    slug_only = doc(
        "Some unrelated blog post about a messaging app being retired",
        source="Mastodon",
        text="Read more at https://web.brid.gy/r/m.blog/2026/08/27/line-voom-demoted/",
    )
    kept, _ = apply_filters([slug_only], "Printed A-Line Kurti")
    assert kept == []
    assert slug_only.filter_reason == "off_topic"


def test_an_all_generic_query_still_matches_on_two_words():
    """If every word is weak, no single one can qualify, but two together can."""
    matching = doc(
        "Found a lovely white cotton set at the market today, really well made",
        source="Reddit",
    )
    one_word = doc(
        "White paint for the living room walls, any recommendations at all?",
        source="Reddit",
    )
    kept, _ = apply_filters([matching, one_word], "White Cotton")
    assert [d.source for d in kept] == ["Reddit"]
    assert one_word.filter_reason == "off_topic"


def test_top_documents_are_spread_across_sources():
    """One chatty platform must not fill every card in the post wall."""
    from app.services.social.agent import _balanced_top_documents

    documents = [
        doc(f"youtube {i}", source="YouTube", engagement=100 - i) for i in range(20)
    ] + [
        doc("pinterest one", source="Pinterest", engagement=1),
        doc("blog one", source="Blogs & reviews", engagement=2),
    ]
    picked = _balanced_top_documents(documents, limit=6)
    sources = {d.source for d in picked}

    # Both quiet sources appear despite being outranked by every Mastodon post.
    assert sources == {"YouTube", "Pinterest", "Blogs & reviews"}
    # The chattiest source still leads, it just no longer monopolises.
    assert picked[0].source == "YouTube"


# ── the market scoping ────────────────────────────────────────────────────────

def test_hashtags_use_the_distinctive_word_not_the_whole_name():
    """#printedalinekurti has no posts; #kurti and #kurtiindia do.

    This is why Instagram returned zero for every product while the Apify token
    was configured and working -- the tag was real syntax for a tag nobody uses.
    """
    from app.services.social import locale

    tags = locale.hashtags("Printed A-Line Kurti")
    assert "kurti" in tags
    assert any(t.startswith("kurti") and t != "kurti" for t in tags)
    assert "printedalinekurti" not in tags


def test_search_phrase_drops_generic_words_and_names_the_market():
    from app.services.social import locale

    phrase = locale.search_phrase("Printed A-Line Kurti")
    assert "kurti" in phrase
    assert "India" in phrase
    # "printed" and "line" identify nothing and only narrow the search to noise.
    assert "line" not in phrase


def test_restriction_note_distinguishes_real_scoping_from_wording():
    """The reader must be able to tell a region parameter from a nudge."""
    from app.services.social import locale

    assert "own region setting" in locale.restriction_note("news")
    assert "no region setting" in locale.restriction_note("pinterest")


def test_a_source_with_no_region_concept_says_so_rather_than_implying_one():
    """Claiming a restriction that was never applied is the failure to avoid."""
    from app.services.social import locale

    note = locale.restriction_note("hackernews")
    assert "Not scoped by region" in note
    assert "Restricted to" not in note


def test_the_tweet_actors_empty_search_sentinel_is_not_read_as_undated_posts():
    """apidojo~tweet-scraper answers an empty search with [{"noResults": ...}].

    Treating those as posts we failed to date reported "10 items lacked a usable
    timestamp" when the truth was simply that nobody had tweeted about it.
    """
    import asyncio

    import httpx

    from app.services.social.apify import XConnector

    connector = XConnector()
    connector.settings = connector.settings.model_copy(update={"apify_token": "test"})

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return [{"noResults": True} for _ in range(10)]

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            return _Response()

    original = httpx.AsyncClient
    httpx.AsyncClient = lambda *a, **k: _Client()
    try:
        documents = asyncio.run(connector.fetch("kurti", 30, 20))
    finally:
        httpx.AsyncClient = original

    assert documents == []
