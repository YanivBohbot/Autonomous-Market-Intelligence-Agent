import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessageChunk

from app.api.models.models import StreamRequest
from app.api.routers._helpers import get_action_description

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/stream", response_class=EventSourceResponse)
async def stream_endpoint(
    request: Request, payload: StreamRequest
) -> AsyncIterable[ServerSentEvent]:
    agent_app = request.app.state.agent_app
    config = {"configurable": {"thread_id": payload.thread_id}}
    inputs = {"question": payload.query}

    try:
        async for token, meta in agent_app.astream(
            inputs, config, stream_mode="messages"
        ):
            if (
                isinstance(token, AIMessageChunk)
                and meta.get("langgraph_node") == "generate"
                and token.content
                and not getattr(token, "tool_call_chunks", None)
            ):
                yield ServerSentEvent(data={"token": token.content}, event="token")

        snapshot = await agent_app.aget_state(config)
        if snapshot.next:
            last_msg = snapshot.values["messages"][-1]
            action = get_action_description(last_msg)
            yield ServerSentEvent(
                data={"action": action, "next_step": str(snapshot.next)},
                event="interrupted",
            )
        else:
            yield ServerSentEvent(data={}, event="done")
    except Exception as exc:
        logger.exception("stream failed for thread %s", payload.thread_id)
        yield ServerSentEvent(data={"error": str(exc)}, event="error")
