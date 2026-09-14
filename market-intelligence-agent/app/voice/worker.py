"""GPT-Live delegation worker.

Attaches to a GPT-Live session (client-delegation mode) over a sideband
WebSocket and bridges its `session.delegation.created` events to the
compiled LangGraph voice workflow (`app.voice.graph`). Spawned as a
background asyncio task per session by
`app/api/routers/gptlive_session.py` right after the browser's WebRTC leg
is created — there is no separate worker process to run.
"""
import logging
import sys

from langchain_core.messages import HumanMessage
from openai import AsyncOpenAI

from app.core.config import settings
from app.voice import transcript_store
from app.voice.hitl import classify_verdict, is_interrupted, resume_with
from app.voice.session import _ToolCallLogger, strip_binary_score_prefix

logger = logging.getLogger("voice.worker")

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

GREETING = "שלום, אני עוזר המודיעין העסקי שלך. איך אוכל לעזור?"


def _trace(msg: str) -> None:
    """Print to stderr unconditionally so a voice QA session can see each
    delegation turn in the server log."""
    print(f"[voice.worker] {msg}", file=sys.stderr, flush=True)


def _extract_reply(state: dict) -> str | None:
    for msg in reversed(state.get("messages", [])):
        content = getattr(msg, "content", None)
        if content and not getattr(msg, "tool_calls", None):
            return strip_binary_score_prefix(str(content))
    return None


async def _handle_delegation(
    connection, agent_app, thread_id: str, delegation_id: str, question: str
) -> None:
    config = {
        "configurable": {"thread_id": thread_id, "actor_id": "mia-agent"},
        "callbacks": [_ToolCallLogger()],
    }
    paused, action = await is_interrupted(agent_app, thread_id)
    if paused:
        verdict = classify_verdict(question)
        if verdict is None:
            confirmation = f"I need confirmation before {action}. Say yes or no."
            await connection.session.commentary.append(
                delegation_id=delegation_id,
                content=confirmation,
            )
            transcript_store.append(thread_id, "assistant", confirmation)
            return
        state = await resume_with(agent_app, thread_id, verdict)
    else:
        state = await agent_app.ainvoke(
            {"messages": [HumanMessage(content=question)], "question": question},
            config,
        )
    reply = _extract_reply(state)
    if reply:
        await connection.session.commentary.append(delegation_id=delegation_id, content=reply)
        transcript_store.append(thread_id, "assistant", reply)


async def run_delegation_worker(session_id: str, thread_id: str, agent_app) -> None:
    """Run until the GPT-Live session closes (WebRTC leg disconnects).

    A delegation event carries no task text — only metadata — so this
    buffers `session.input_transcript.delta` fragments and treats the
    accumulated transcript as the question when
    `session.delegation.created` fires.
    """
    _trace(f"attaching sideband session_id={session_id} thread_id={thread_id}")
    transcript_buffer = ""
    async with _client.live.sideband.connect(session_id=session_id) as connection:
        # Bypass the graph for the greeting — same rationale as the old
        # LiveKit worker's session.say(): the graph is slow (LLM + tools),
        # and if the user speaks during the greeting an in-flight run
        # getting cancelled can leave the checkpointer in a bad state.
        await connection.session.commentary.append(delegation_id=None, content=GREETING)
        transcript_store.append(thread_id, "assistant", GREETING)

        async for event in connection:
            if event.type == "session.input_transcript.delta":
                transcript_buffer += event.delta
            elif event.type == "session.delegation.created":
                question = transcript_buffer.strip()
                transcript_buffer = ""
                _trace(f"delegation.created id={event.delegation.id} question={question!r}")
                if question:
                    transcript_store.append(thread_id, "user", question)
                try:
                    await _handle_delegation(
                        connection, agent_app, thread_id, event.delegation.id, question
                    )
                except Exception:
                    logger.exception("voice delegation failed (session=%s)", session_id)
                    await connection.session.commentary.append(
                        delegation_id=event.delegation.id,
                        content="Sorry, something went wrong handling that. Please try again.",
                    )
            elif event.type == "error":
                logger.warning("GPT-Live sideband error (session=%s): %s", session_id, event)
            elif event.type == "session.closed":
                _trace(f"session closed session_id={session_id} reason={event.reason}")
                break
    _trace(f"worker exiting session_id={session_id}")
