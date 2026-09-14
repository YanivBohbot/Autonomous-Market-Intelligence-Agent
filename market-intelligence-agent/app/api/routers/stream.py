import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessageChunk, ToolMessage

from app.agent.tools.mcp_clients.browser_client import SCREENSHOT_TOOL_NAME
from app.api.models.models import StreamRequest
from app.api.routers._helpers import get_action_description

logger = logging.getLogger(__name__)
router = APIRouter()


def _tool_names_from_update(update) -> list[str] | None:
    """Pull tool-call names off the last message in a node's state update."""
    if not isinstance(update, dict):
        return None
    messages = update.get("messages")
    if not messages:
        return None
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return None
    return [tc["name"] for tc in tool_calls]


def _screenshot_urls_from_update(update) -> list[str]:
    """Pull workspace-relative screenshot paths off any browser_take_screenshot
    ToolMessage in a node's state update, as URLs the /workspace router serves."""
    if not isinstance(update, dict):
        return []
    messages = update.get("messages") or []
    urls = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == SCREENSHOT_TOOL_NAME:
            filename = str(msg.content).rsplit("/", 1)[-1]
            urls.append(f"/workspace/screenshots/{filename}")
    return urls


@router.post("/stream", response_class=EventSourceResponse)
async def stream_endpoint(
    request: Request, payload: StreamRequest
) -> AsyncIterable[ServerSentEvent]:
    agent_app = request.app.state.agent_app
    config = {
        "configurable": {
            "thread_id": payload.thread_id,
            "actor_id": "mia-agent",
        }
    }
    inputs = {"question": payload.query}

    try:
        async for mode, chunk in agent_app.astream(
            inputs, config, stream_mode=["updates", "messages"]
        ):
            if mode == "updates":
                for node_name, update in chunk.items():
                    yield ServerSentEvent(
                        data={
                            "node": node_name,
                            "tool_calls": _tool_names_from_update(update),
                        },
                        event="node",
                    )
                    for url in _screenshot_urls_from_update(update):
                        yield ServerSentEvent(data={"url": url}, event="screenshot")
            elif mode == "messages":
                token, meta = chunk
                if (
                    isinstance(token, AIMessageChunk)
                    and meta.get("langgraph_node") == "generate"
                    and token.content
                    and not getattr(token, "tool_call_chunks", None)
                ):
                    yield ServerSentEvent(
                        data={"token": token.content}, event="token"
                    )

        snapshot = await agent_app.aget_state(config)
        if snapshot.next and "approval" in snapshot.next:
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
