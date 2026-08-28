"""Record a real social harvest for offline replay.

Public sources are not always reachable -- a demo on conference wi-fi, a
rate-limited IP, an evaluator running this months from now. Recording a fixture
captures a genuine harvest so the system can replay it and label the response
``provenance="fixture"`` instead of silently substituting invented data.

    python -m scripts.record_fixture "Christmas decorations"
    python -m scripts.record_fixture "Christmas decorations" --lookback-days 60
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.core.logging_config import configure_logging
from app.services.social.agent import _harvest
from app.services.social.fixtures import save_fixture

LOG = logging.getLogger("record_fixture")


async def record(query: str, lookback_days: int) -> int:
    settings = get_settings()
    documents, signals, statuses = await _harvest(
        query, lookback_days, settings.social_max_documents
    )

    for status in statuses:
        LOG.info("  %-12s %-12s n=%-4d %s",
                 status.name, status.status, status.documents, status.detail[:70])

    if not documents:
        LOG.error("No documents harvested for %r; nothing to record.", query)
        return 1

    path = save_fixture(query, documents, signals)
    LOG.info("Recorded %d documents and %d signal readings -> %s",
             len(documents), len(signals), path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query", help="product or brand to harvest")
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args(argv)

    configure_logging("INFO")
    return asyncio.run(record(args.query, args.lookback_days))


if __name__ == "__main__":
    sys.exit(main())
