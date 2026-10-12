"""The assistant endpoint.

Two shapes of the same turn. ``POST /chat`` returns the finished answer, which is
what a script or a test wants. ``POST /chat/stream`` emits the sub-agent's own
stage transitions over server-sent events while the work happens, which is what a
person wants when the underlying tool takes fifteen seconds -- and the social
harvest sometimes ninety.

The stages are real. They are emitted from inside the pipeline as each step
begins, exactly as the forecast stream already does, so a step that is skipped
never arrives and a slow one visibly takes its time. Nothing here fabricates
progress to keep a bar moving.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import get_db
from app.services.agents.orchestrator import answer, default_dataset, product_catalogue
from app.services.agents.schemas import ChatAnswer, ChatRequest

LOG = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatAnswer, summary="Ask the assistant a question")
async def chat(request: ChatRequest, session: Session = Depends(get_db)) -> ChatAnswer:
    return await answer(request, session=session)


@router.post("/chat/stream", summary="Ask the assistant, streaming the agent's progress")
async def chat_stream(
    request: ChatRequest, session: Session = Depends(get_db)
) -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_stage(stage: str, detail: str) -> None:
        # Sub-agents that block run in a worker thread, so the hop back onto the
        # loop is required rather than defensive.
        loop.call_soon_threadsafe(
            queue.put_nowait,
            json.dumps({"type": "stage", "stage": stage, "detail": detail}),
        )

    async def run() -> None:
        try:
            result = await answer(request, session=session, on_stage=on_stage)
            queue.put_nowait(json.dumps({
                "type": "done", "result": result.model_dump(mode="json"),
            }))
        except AppError as exc:
            queue.put_nowait(json.dumps({
                "type": "error", "error": exc.to_payload()["error"],
            }))
        except Exception as exc:
            LOG.exception("Streamed chat turn failed")
            queue.put_nowait(json.dumps({
                "type": "error",
                "error": {"code": "internal_error", "message": str(exc)},
            }))
        finally:
            queue.put_nowait("__end__")

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                payload = await queue.get()
                if payload == "__end__":
                    break
                yield f"data: {payload}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/suggestions", summary="Opening questions grounded in the real data")
async def chat_suggestions(dataset: str | None = None) -> dict:
    """Starter prompts naming products that actually exist.

    A chat surface that opens with invented examples teaches the user to ask
    about things the tool has never heard of. These are built from the catalogue,
    so every one of them works.
    """
    dataset_id = dataset or default_dataset()
    products = product_catalogue(dataset_id)
    lead = products[0] if products else None
    second = products[1] if len(products) > 1 else lead

    if lead is None:
        return {
            "dataset": dataset_id,
            "suggestions": [
                {"label": "What data do I have?", "intent": "catalogue"},
                {"label": "What can you do?", "intent": "capability"},
            ],
        }

    return {
        "dataset": dataset_id,
        "suggestions": [
            {"label": f"How many {lead} will I sell next month?", "intent": "forecast"},
            {"label": "Which product is falling fastest?", "intent": "sales_history"},
            {"label": f"What are people saying about {second}?", "intent": "social"},
            {"label": f"How accurate is the {lead} forecast?", "intent": "accuracy"},
            {"label": "What data do I have?", "intent": "catalogue"},
        ],
    }
