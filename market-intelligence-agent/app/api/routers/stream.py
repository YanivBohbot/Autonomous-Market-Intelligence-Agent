import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessageChunk

from app.agent.graph import agent_app
from app.api.models.models import StreamRequest
from app.api.routers._helpers import get_action_description

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/stream", response_class=EventSourceResponse)
async def stream_endpoint(request: StreamRequest) -> AsyncIterable[ServerSentEvent]:
    config = {"configurable": {"thread_id": request.thread_id}}
    inputs = {"question": request.query}

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

        snapshot = agent_app.get_state(config)
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
        logger.exception("stream failed for thread %s", request.thread_id)
        yield ServerSentEvent(data={"error": str(exc)}, event="error")
