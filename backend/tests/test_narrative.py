"""The insight layer: payload construction, the number guard, and the fallback.

The guard is the load-bearing test here. Everything else in this project earns trust
by being measured; an LLM that invents one plausible statistic would undo that, so
the guard must catch it before a user ever sees it.
"""

from __future__ import annotations

import pytest

from app.services.narrative import guard
from app.services.narrative.briefing import build_template_brief
from app.services.narrative.schemas import Finding, OwnerBrief

PAYLOAD = {
    "product": "Cargo Shorts",
    "horizon_days": 30,
    "forecast": {
        "total_units": 1223.0,
        "daily_average": 40.8,
        "recent_daily_average": 131.9,
        "change_vs_recent_pct": -69.1,
        "busiest_day": "2011-12-13",
        "busiest_day_units": 78.2,
        "quiet_day_units": 0.0,
        "safe_stock_total": 4721.0,
        "low_end_total": 210.0,
    },
    "history": {"days_of_data": 738, "days_with_sales_pct": 81.6,
                "quality": "good", "warnings": []},
    "model": {"name": "chronos-2", "uses_external_signals": True},
    "accuracy": {"checked_on_past_periods": 5, "typical_error_units": 67.0,
                 "beats_simple_guess": True, "better_than_guess_pct": 44.0,
                 "range_was_right_pct": 81.0, "improvement_over_baseline_pct": 38.4},
    "external_signals": {"tested": ["calendar", "holiday"], "used": ["holiday"],
                         "location": "United Kingdom", "results": [],
                         "net_accuracy_gain_pct": 0.74},
}


# ── the guard ─────────────────────────────────────────────────────────────────

def test_supported_numbers_pass():
    text = (
        "Cargo Shorts should sell about 1,223 units over the next 30 days, "
        "averaging 40.8 a day against 131.9 recently."
    )
    assert guard.check(text, PAYLOAD) == []


def test_invented_statistic_is_caught():
    """The exact failure this guard exists for: a plausible number from nowhere."""
    text = "Sales rose 87.3% last quarter and margins improved to 42.7%."
    flagged = guard.check(text, PAYLOAD)
    assert "87.3" in flagged
    assert "42.7" in flagged


def test_thousands_separators_and_rounding_are_tolerated():
    assert guard.check("about 1223 units", PAYLOAD) == []
    assert guard.check("about 1,223 units", PAYLOAD) == []
    # 40.8 rounded to 41 is the same number to a reader.
    assert guard.check("roughly 41 a day", PAYLOAD) == []


def test_sign_is_not_policed_only_magnitude():
    """A payload value of -69.1 legitimately becomes "fell about 69%" in prose."""
    assert guard.check("demand falls about 69.1%", PAYLOAD) == []
    assert guard.check("demand falls about 69%", PAYLOAD) == []


def test_ratios_may_be_written_as_percentages():
    payload = {"coverage": 0.81}
    assert guard.check("the range was right 81% of the time", payload) == []


def test_small_counting_numbers_are_not_flagged():
    """'the next 7 days' is English, not a statistic."""
    assert guard.check("There are 3 things to watch over the next 7 days.", PAYLOAD) == []


def test_guard_walks_a_whole_brief():
    brief = OwnerBrief(
        headline="Demand falls 69.1%.",
        summary="About 1,223 units.",
        findings=[Finding(text="Margins hit 88.4%.")],
    )
    flagged = guard.check_brief(brief, PAYLOAD)
    assert "88.4" in flagged
    # The payload holds -69.1; prose that says "falls 69.1%" is correct, not invented.
    assert "69.1" not in flagged


def test_collect_numbers_reaches_nested_values():
    found = guard.collect_numbers({"a": {"b": [1.5, {"c": 99.0}]}})
    assert 1.5 in found
    assert 99.0 in found


# ── template brief ────────────────────────────────────────────────────────────

def test_template_brief_uses_only_payload_numbers():
    """The deterministic path must pass its own guard by construction."""
    brief = build_template_brief(PAYLOAD)
    assert guard.check_brief(brief, PAYLOAD) == []


def test_template_brief_avoids_statistics_jargon():
    brief = build_template_brief(PAYLOAD)
    text = " ".join([
        brief.headline, brief.summary, brief.confidence_note,
        *[f.text for f in brief.findings], *[a.text for a in brief.actions],
    ]).lower()

    for term in ("mase", "rmse", "smape", "quantile", "confidence interval",
                 "covariate", "p-value", "heteroskedas"):
        assert term not in text, f"jargon leaked into the owner brief: {term}"


def test_template_brief_states_direction_and_stock_number():
    brief = build_template_brief(PAYLOAD)
    assert "fall" in brief.headline.lower()
    assert "4,721" in brief.summary


def test_template_brief_warns_when_the_model_is_no_better_than_guessing():
    payload = {**PAYLOAD, "accuracy": {**PAYLOAD["accuracy"], "beats_simple_guess": False}}
    brief = build_template_brief(payload)
    assert "no better" in brief.confidence_note.lower()
    assert any("did not beat" in f.text.lower() for f in brief.findings)


def test_template_brief_admits_when_accuracy_is_unmeasured():
    payload = {k: v for k, v in PAYLOAD.items() if k != "accuracy"}
    brief = build_template_brief(payload)
    assert "not enough history" in brief.confidence_note.lower()


# ── availability reporting ────────────────────────────────────────────────────

def test_client_reports_why_it_is_unavailable():
    from app.services.narrative import client

    if not client.is_available():
        reason = client.unavailable_reason()
        assert reason
        assert "RETAILIQ_GOOGLE_API_KEY" in reason or "disabled" in reason


@pytest.mark.slow
@pytest.mark.network
def test_gemini_brief_when_a_key_is_configured():
    from app.services.narrative import client

    if not client.is_available():
        pytest.skip("no Google AI Studio key configured")

    envelope = client.generate_brief(PAYLOAD)
    assert envelope is not None
    assert envelope.source in {"llm", "none"}
    if envelope.source == "llm":
        assert envelope.brief.headline
        assert envelope.guard_flags == []


# ── the social brief ─────────────────────────────────────────────────────────
def _social_response(**overrides):
    from datetime import UTC, datetime

    from app.schemas.social import (
        ConnectorStatus,
        PlatformStats,
        SentimentModelInfo,
        SocialResponse,
        TrendingTerm,
    )

    defaults = {
        "query": "cake stand",
        "generated_at": datetime.now(UTC),
        "lookback_days": 30,
        "cached": False,
        "provenance": "live",
        "connectors": [
            ConnectorStatus(name="news", status="ok", documents=17, detail="17 documents"),
            ConnectorStatus(name="pinterest", status="error", detail="HTTP 403"),
        ],
        "sentiment_model": SentimentModelInfo(
            name="twitter-roberta", kind="transformer", detail=""
        ),
        "total_documents": 83,
        "filtered_documents": 23,
        "total_mentions": 83,
        "overall_sentiment": 0.30,
        "overall_label": "positive",
        "platforms": [
            PlatformStats(platform="News", documents=16, mentions=16, engagement_total=0,
                          engagement_rate=0, sentiment_score=0.58, positive_share=0.7,
                          negative_share=0.1, available=True),
            PlatformStats(platform="Hacker News", documents=22, mentions=22,
                          engagement_total=0, engagement_rate=0, sentiment_score=-0.31,
                          positive_share=0.2, negative_share=0.5, available=True),
            PlatformStats(platform="Google Trends", documents=92, mentions=0,
                          engagement_total=1, engagement_rate=44.2, sentiment_score=0.0,
                          positive_share=0, negative_share=0, available=True,
                          note="search interest"),
        ],
        "timeline": [],
        "trending_terms": [
            TrendingTerm(term="cake", count=12, share=0.1, sentiment_score=0.2,
                         sentiment_label="positive"),
        ],
        "top_documents": [],
        "narrative": [],
        "narrative_source": "template",
    }
    defaults.update(overrides)
    return SocialResponse(**defaults)


def test_search_interest_is_kept_out_of_the_mood_figure():
    """Trends measures attention, not approval. Averaging it in is a category error."""
    from app.services.narrative.social_briefing import build_payload

    payload = build_payload(_social_response())
    mood_platforms = {p["platform"] for p in payload["mood"]["by_platform"]}
    assert "Google Trends" not in mood_platforms
    assert payload["attention_not_approval"][0]["platform"] == "Google Trends"


def test_the_social_template_brief_states_its_evidence():
    from app.services.narrative.social_briefing import build_payload, build_template_brief

    brief = build_template_brief(build_payload(_social_response()))
    assert "83" in brief.headline
    # How much evidence it rests on is part of the hero, not a footnote.
    assert "83 documents" in brief.evidence_note
    assert "1 of 2" in brief.evidence_note
    text = " ".join(f.text for f in brief.findings)
    # A source that could not be reached must be named, not silently omitted.
    assert "pinterest" in text


def test_thin_evidence_is_called_out_rather_than_smoothed_over():
    from app.services.narrative.social_briefing import build_payload, build_template_brief

    brief = build_template_brief(build_payload(_social_response(total_documents=6)))
    text = " ".join(f.text for f in brief.findings)
    assert "thin" in text.lower()


def test_an_empty_harvest_still_produces_an_explanation():
    """An empty result is where a reader most needs to be told what was tried.

    This asserts the *template* renderer directly rather than build_brief, because
    build_brief prefers Gemini whenever a key is configured -- and this behaviour
    has to hold on the path that cannot call anything.
    """
    from app.services.narrative.social_briefing import build_payload, build_template_brief

    brief = build_template_brief(build_payload(_social_response(
        total_documents=0, filtered_documents=0, platforms=[], trending_terms=[],
        overall_sentiment=0.0, overall_label="neutral", provenance="none",
    )))
    assert "Nothing public was found" in brief.headline
    # It must not imply neutrality: no documents is not the same as no opinion.
    assert "not that" in brief.summary


def test_the_brief_prefers_gemini_when_a_key_is_present(monkeypatch):
    """And falls back to the template when it is not, saying which ran."""
    from app.services.narrative import social_briefing

    monkeypatch.setattr(social_briefing.client, "generate_social_brief", lambda p: None)
    monkeypatch.setattr(social_briefing.client, "unavailable_reason", lambda: "no key")
    envelope = social_briefing.build_brief(_social_response())
    assert envelope.source == "template"
    assert envelope.warnings == ["no key"]


def test_the_social_brief_passes_through_the_same_number_guard():
    """A social brief that invents a figure is as damaging as a forecast one."""
    from app.services.narrative import guard
    from app.services.narrative.social_briefing import build_payload

    payload = build_payload(_social_response())
    assert guard.check("83 documents were analysed", payload) == []
    assert guard.check("4,912 documents were analysed", payload) == ["4,912"]
