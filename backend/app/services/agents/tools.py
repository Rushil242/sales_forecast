"""The tool surface, over the service layer rather than over HTTP.

This mirrors ``app/mcp_server.py`` deliberately -- the same seven capabilities,
the same service functions -- but returns Python objects and records timing
instead of serialising for a wire protocol. An in-process call also removes a
whole HTTP round trip per tool from a conversational turn, which is most of what
"fast" means here.

Every tool is wrapped so that a failure becomes a recorded, reportable
``ToolInvocation`` rather than an exception that collapses the turn. A sub-agent
that could not reach one source should still answer from the others and say
which one it lost -- the same discipline the social harvest already follows.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.errors import AppError
from app.services.agents.schemas import ToolInvocation

LOG = logging.getLogger(__name__)


class ToolRun:
    """Result of one tool call: the value, and the record of having called it."""

    __slots__ = ("value", "record")

    def __init__(self, value: Any, record: ToolInvocation) -> None:
        self.value = value
        self.record = record

    @property
    def ok(self) -> bool:
        return self.record.ok


def call(tool: str, fn: Callable[..., Any], /, **kwargs: Any) -> ToolRun:
    """Invoke a service-layer function as a tool, capturing timing and failure.

    ``AppError`` is kept distinct from an unexpected exception on purpose. An
    ``insufficient_data`` refusal is a *correct* outcome the assistant must
    relay in the owner's language; an internal error is a bug the assistant
    should admit to rather than dress up as an answer.
    """
    started = time.perf_counter()
    try:
        value = fn(**kwargs)
    except AppError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        LOG.info("Tool %s refused: %s", tool, exc.code)
        return ToolRun(None, ToolInvocation(
            tool=tool, arguments=_safe_args(kwargs), ok=False,
            duration_ms=elapsed, error=f"{exc.code}: {exc.message}",
        ))
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        LOG.exception("Tool %s failed", tool)
        return ToolRun(None, ToolInvocation(
            tool=tool, arguments=_safe_args(kwargs), ok=False,
            duration_ms=elapsed, error=f"{type(exc).__name__}: {exc}",
        ))

    elapsed = int((time.perf_counter() - started) * 1000)
    return ToolRun(value, ToolInvocation(
        tool=tool, arguments=_safe_args(kwargs), ok=True, duration_ms=elapsed,
    ))


async def call_async(tool: str, fn: Callable[..., Any], /, **kwargs: Any) -> ToolRun:
    """Async twin of :func:`call`, for the social harvest."""
    started = time.perf_counter()
    try:
        value = await fn(**kwargs)
    except AppError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ToolRun(None, ToolInvocation(
            tool=tool, arguments=_safe_args(kwargs), ok=False,
            duration_ms=elapsed, error=f"{exc.code}: {exc.message}",
        ))
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        LOG.exception("Async tool %s failed", tool)
        return ToolRun(None, ToolInvocation(
            tool=tool, arguments=_safe_args(kwargs), ok=False,
            duration_ms=elapsed, error=f"{type(exc).__name__}: {exc}",
        ))

    elapsed = int((time.perf_counter() - started) * 1000)
    return ToolRun(value, ToolInvocation(
        tool=tool, arguments=_safe_args(kwargs), ok=True, duration_ms=elapsed,
    ))


def _safe_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Arguments as displayable scalars.

    The trace is rendered in the browser, so a whole ``Dataset`` or ORM session
    must not travel with it -- both are unserialisable and neither tells the
    reader anything.
    """
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in ("session", "dataset_obj", "on_stage"):
            continue
        scalar = isinstance(value, (str, int, float, bool)) or value is None
        flat_dict = isinstance(value, dict) and all(
            isinstance(v, (str, int, float, bool)) for v in value.values()
        )
        out[key] = value if (scalar or flat_dict) else type(value).__name__
    return out
