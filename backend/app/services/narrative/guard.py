"""Verify that every number the model wrote actually came from the data.

The failure mode this exists to prevent
---------------------------------------
An LLM given real statistics will happily add plausible ones. "Sales rose 12% last
quarter" reads exactly like the measured figures around it, and a business owner has
no way to tell them apart. In a system whose entire premise is that its numbers are
measured rather than asserted, one invented statistic is worse than no narrative.

How it works
------------
Extract every numeric token from the generated text, extract every number reachable
in the payload the model was given, and flag any figure in the text that has no
counterpart in the payload. Matching is tolerant in the ways that matter: 1,223 and
1223 are the same number, 40.8 matches 40.83 after rounding, percentages match
whether written as 0.384 or
38.4, and **magnitude is compared rather than sign** -- a payload value of -69.1
legitimately becomes "fell about 69%" in prose. Sign is deliberately not policed:
the purpose here is catching fabricated magnitudes, and flagging every correctly
worded decrease would make the guard useless.

A flagged brief is not shown. The deterministic template renderer runs instead, and
the response records why.
"""

from __future__ import annotations

import logging
import re
from typing import Any

LOG = logging.getLogger(__name__)

# Numbers with optional thousands separators, decimals and a leading sign.
_NUMBER = re.compile(r"[-+]?\d[\d,]*\.?\d*")

# Small integers appear constantly in ordinary prose ("3 things", "the next 7 days")
# and flagging them would make the guard useless. Anything at or below this that is
# also a whole number is ignored.
TRIVIAL_MAX = 31

# Relative tolerance when comparing a written figure to a payload value.
TOLERANCE = 0.02


def _to_float(token: str) -> float | None:
    try:
        return float(token.replace(",", "").replace("+", ""))
    except ValueError:
        return None


def collect_numbers(payload: Any, into: set[float] | None = None) -> set[float]:
    """Every number reachable anywhere in the payload, plus useful derivations."""
    values = into if into is not None else set()

    if isinstance(payload, bool):
        return values
    if isinstance(payload, (int, float)):
        value = abs(float(payload))
        values.add(value)
        values.add(round(value))
        values.add(round(value, 1))
        values.add(round(value, 2))
        # A ratio in the payload is frequently written as a percentage in the text.
        if -1.0 <= value <= 1.0:
            values.add(round(value * 100, 1))
            values.add(round(value * 100))
        # And vice versa.
        values.add(round(value / 100, 3))
        return values

    if isinstance(payload, str):
        for token in _NUMBER.findall(payload):
            number = _to_float(token)
            if number is not None:
                collect_numbers(number, values)
        return values

    if isinstance(payload, dict):
        for item in payload.values():
            collect_numbers(item, values)
        return values

    if isinstance(payload, (list, tuple, set)):
        for item in payload:
            collect_numbers(item, values)
        return values

    return values


def _is_supported(number: float, known: set[float]) -> bool:
    number = abs(number)
    if number in known:
        return True
    # Whole small numbers are ordinary English, not statistics.
    if abs(number) <= TRIVIAL_MAX and float(number).is_integer():
        return True
    for candidate in known:
        if candidate == 0:
            if abs(number) < 1e-9:
                return True
            continue
        if abs(number - candidate) / abs(candidate) <= TOLERANCE:
            return True
    return False


def check(text: str, payload: Any) -> list[str]:
    """Return the figures in ``text`` that the payload does not support."""
    known = collect_numbers(payload)
    flagged: list[str] = []

    for token in _NUMBER.findall(text or ""):
        number = _to_float(token)
        if number is None:
            continue
        if not _is_supported(number, known):
            flagged.append(token)

    if flagged:
        LOG.warning(
            "Narrative guard flagged unsupported figures: %s", ", ".join(sorted(set(flagged)))
        )
    return sorted(set(flagged))


def check_brief(brief: Any, payload: Any) -> list[str]:
    """Run :func:`check` over every text field of a brief."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif hasattr(value, "model_dump"):
            walk(value.model_dump())

    walk(brief)
    return check(" ".join(parts), payload)
