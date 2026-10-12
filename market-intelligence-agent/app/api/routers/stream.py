import logging
import re
from collections.abc import AsyncIterable
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessageChunk, ToolMessage

from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING
from app.agent.tools.mcp_clients.browser_client import SCREENSHOT_TOOL_NAME
from app.api.models.models import StreamRequest
from app.api.routers._helpers import (
    get_action_description,
    pending_interrupt_from_snapshot,
)

_SCREENSHOT_LINK_RE = re.compile(r"\[Screenshot[^\]]*\]\(([^)]+)\)")
_STREAMABLE_NODES = {"agent", "model", "synthesize"}

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


def _screenshot_filename(content) -> str | None:
    """Extract just the PNG filename from a browser_take_screenshot
    ToolMessage's content, whose shape differs by backend:

    - @playwright/mcp (local dev): a list of MCP content blocks, e.g.
      [{"type": "text", "text": "### Result\\n- [Screenshot of viewport]"
        "(./evidence.png)\\n### Ran Playwright code\\n...", "id": "..."}]
      — the filename is a markdown link inside the block's 'text'.
    - app/mcp/browser/server.py (BROWSER_BACKEND=agentcore): a plain
      workspace-relative path string, e.g. "screenshots/evidence.png".
    """
    if isinstance(content, list):
        text = next(
            (b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"),
            None,
        )
    else:
        text = content
    if not text:
        return None
    match = _SCREENSHOT_LINK_RE.search(text)
    raw = match.group(1) if match else text
    return Path(raw).name


# Nodes that add a blocking AIMessage straight to state instead of streaming
# it: the supervisor node, which copies the card guard's warning into state,
# and OpenAIModerationMiddleware's hooks inside a specialist subgraph.
_STATIC_MESSAGE_NODES = {
    "supervisor",
    "OpenAIModerationMiddleware.before_model",
    "OpenAIModerationMiddleware.after_model",
}


def _inside_supervisor(namespace) -> bool:
    """Events from the supervisor's own router agent (a create_agent run
    inside the supervisor node): its "model" node streams the routing JSON,
    which must never reach the chat, and its internal nodes are not graph
    steps the client tracks. The card warning still arrives once, through
    the supervisor node's own update."""
    return bool(namespace) and str(namespace[0]).startswith("supervisor:")


def _static_message_content(node_name: str, update) -> str | None:
    """A guardrail's blocking AIMessage is added straight to graph
    state, never streamed as an AIMessageChunk (that only happens for model
    calls) -- so without this, a blocked turn produced zero token events and
    the client never saw the warning, even though the block itself worked."""
    if node_name not in _STATIC_MESSAGE_NODES or not isinstance(update, dict):
        return None
    messages = update.get("messages")
    if not messages:
        return None
    content = messages[-1].content or None
    # The supervisor writes a message to state only for a card block; any
    # other text there is not something to show as a chat token.
    if node_name == "supervisor" and content != SENSITIVE_DATA_WARNING:
        return None
    return content


def _screenshot_urls_from_update(update) -> list[str]:
    """Pull workspace-relative screenshot URLs off any browser_take_screenshot
    ToolMessage in a node's state update, for the /workspace router to serve."""
    if not isinstance(update, dict):
        return []
    messages = update.get("messages") or []
    urls = []
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.name == SCREENSHOT_TOOL_NAME:
            filename = _screenshot_filename(msg.content)
            if filename:
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
    coordinator = request.app.state.turn_coordinator
    lease = await coordinator.try_acquire(
        payload.thread_id, f"text:stream:{uuid4()}"
    )
    if lease is None:
        owner = await coordinator.owner(payload.thread_id)
        error = (
            "Voice mode is active for this thread."
            if owner and owner.startswith("voice:")
            else "Another turn is active for this thread."
        )
        yield ServerSentEvent(data={"error": error}, event="error")
        return

    try:
        async for namespace, mode, chunk in agent_app.astream(
            inputs,
            config,
            stream_mode=["updates", "messages"],
            subgraphs=True,
        ):
            if _inside_supervisor(namespace):
                continue
            if mode == "updates":
                for node_name, update in chunk.items():
                    yield ServerSentEvent(
                        data={
                            "node": node_name,
                            "tool_calls": _tool_names_from_update(update),
                        },
                        event="node",
                    )
                    warning = _static_message_content(node_name, update)
                    if warning:
                        yield ServerSentEvent(
                            data={"token": warning}, event="token"
                        )
                    for url in _screenshot_urls_from_update(update):
                        yield ServerSentEvent(data={"url": url}, event="screenshot")
            elif mode == "messages":
                token, meta = chunk
                if (
                    isinstance(token, AIMessageChunk)
                    and meta.get("langgraph_node") in _STREAMABLE_NODES
                    and token.content
                    and not getattr(token, "tool_call_chunks", None)
                ):
                    yield ServerSentEvent(
                        data={"token": token.content}, event="token"
                    )

        snapshot = await agent_app.aget_state(config, subgraphs=True)
        pending = pending_interrupt_from_snapshot(snapshot)
        if pending is not None:
            requests = pending.value.get("action_requests")
            action_request = requests[0] if isinstance(requests, list) and requests else None
            action = get_action_description(pending.last_message, action_request)
            yield ServerSentEvent(
                data={"action": action, "next_step": str(snapshot.next)},
                event="interrupted",
            )
        else:
            yield ServerSentEvent(data={}, event="done")
    except Exception as exc:
        logger.exception("stream failed for thread %s", payload.thread_id)
        yield ServerSentEvent(data={"error": str(exc)}, event="error")
    finally:
        await coordinator.release(lease)
