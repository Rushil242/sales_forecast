"""Offline fixture replay.

Live public sources are not always reachable -- an exam-hall demo on conference
wi-fi, a rate-limited IP, an evaluator running the project six months from now.
Rather than silently substituting invented numbers in those situations, the agent
replays a previously *recorded* harvest and labels the response
``provenance="fixture"`` so the UI can say plainly that the data is a replay.

Fixtures are recorded from real harvests by ``scripts/record_fixture.py``; this
module never synthesises documents.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.services.social.base import RawDocument

LOG = logging.getLogger(__name__)


def _slug(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:80] or "query"


def fixture_dir() -> Path:
    return get_settings().data_dir / "fixtures"


def fixture_path(query: str) -> Path:
    return fixture_dir() / f"{_slug(query)}.json"


def available_fixtures() -> list[str]:
    directory = fixture_dir()
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.json"))


def save_fixture(query: str, documents: list[RawDocument], signals: dict[str, float]) -> Path:
    """Persist a real harvest for later replay."""
    directory = fixture_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = fixture_path(query)

    payload = {
        "query": query,
        "recorded_at": datetime.now(UTC).isoformat(),
        "signals": signals,
        "documents": [
            {
                "source": d.source,
                "title": d.title,
                "text": d.text,
                "url": d.url,
                "author": d.author,
                "published_at": d.published_at.isoformat(),
                "engagement": d.engagement,
                "extra": d.extra,
            }
            for d in documents
        ],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    LOG.info("Recorded %d documents for '%s' -> %s", len(documents), query, path)
    return path


def load_fixture(query: str) -> tuple[list[RawDocument], dict[str, float], datetime] | None:
    """Load a recorded harvest, or ``None`` if there is none for this query."""
    path = fixture_path(query)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("Fixture %s is unreadable: %s", path.name, exc)
        return None

    documents = [
        RawDocument(
            source=item["source"],
            title=item["title"],
            text=item.get("text", ""),
            url=item.get("url"),
            author=item.get("author"),
            published_at=datetime.fromisoformat(item["published_at"]),
            engagement=float(item.get("engagement", 0.0)),
            extra=item.get("extra", {}),
        )
        for item in payload.get("documents", [])
    ]
    recorded_at = datetime.fromisoformat(payload["recorded_at"])
    LOG.info("Replaying fixture for '%s': %d documents recorded %s",
             query, len(documents), recorded_at.date())
    return documents, payload.get("signals", {}), recorded_at
