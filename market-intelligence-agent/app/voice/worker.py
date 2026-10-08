"""GPT-Live delegation worker.

Attaches to a GPT-Live session (client-delegation mode) over a sideband
WebSocket and bridges its `session.delegation.created` events to the
compiled LangGraph voice workflow (`app.voice.graph`). Spawned as a
background asyncio task per session by
`app/api/routers/gptlive_session.py` right after the browser's WebRTC leg
is created — there is no separate worker process to run.
"""
import asyncio
import logging
import sys
from contextlib import suppress

from langchain_core.messages import HumanMessage
from openai import AsyncOpenAI

from app.core.config import settings
from app.voice import transcript_store
from app.voice.hitl import classify_verdict, is_interrupted, resume_with
from app.voice.session import _ToolCallLogger, strip_binary_score_prefix

logger = logging.getLogger("voice.worker")

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

GREETING = "שלום, אני עוזר המודיעין העסקי שלך. איך אוכל לעזור?"
RESEARCH_GREETING = "Voice mode is ready. How can I help?"


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


async def _handle_research_delegation(
    connection,
    research_runtime,
    activity_store,
    thread_id: str,
    delegation_id: str,
    question: str,
    is_closed,
) -> None:
    pending = activity_store.snapshot(thread_id)["pending"]
    if pending:
        verdict = classify_verdict(question)
        if verdict is None:
            reply = "Say Approve or Reject, or use the approval card."
        else:
            decision = (
                {"type": "approve"}
                if verdict == "approve"
                else {"type": "reject", "message": "Rejected by user."}
            )
            result = await research_runtime.resolve(
                thread_id, pending["interrupt_id"], [decision]
            )
            reply = result.response
    else:
        result = await research_runtime.run_turn(thread_id, question)
        reply = result.response

    if reply and not is_closed():
        await connection.session.commentary.append(
            delegation_id=delegation_id,
            content=reply,
        )


async def _restore_research_phase(activity_store, thread_id: str) -> None:
    await asyncio.sleep(0.35)
    pending = activity_store.snapshot(thread_id)["pending"]
    activity_store.set_phase(
        thread_id, "approval_required" if pending else "listening"
    )


def _consume_task(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    with suppress(Exception):
        task.result()


async def run_delegation_worker(
    session_id: str,
    thread_id: str,
    agent_app,
    *,
    surface: str = "classic",
    research_runtime=None,
    activity_store=None,
    lease=None,
    turn_coordinator=None,
) -> None:
    """Run until the GPT-Live session closes (WebRTC leg disconnects).

    A delegation event carries no task text — only metadata — so this
    buffers `session.input_transcript.delta` fragments and treats the
    accumulated transcript as the question when
    `session.delegation.created` fires.
    """
    _trace(
        f"attaching sideband session_id={session_id} thread_id={thread_id} surface={surface}"
    )
    is_research = surface == "research"
    if is_research and (
        research_runtime is None
        or activity_store is None
        or lease is None
        or turn_coordinator is None
    ):
        raise ValueError("Research voice worker dependencies are required.")

    transcript_buffer = ""
    active_delegation: asyncio.Task | None = None
    speaking_reset: asyncio.Task | None = None
    closed = False
    worker_error: Exception | None = None

    async def handle(connection, delegation_id: str, question: str) -> None:
        try:
            if is_research:
                await _handle_research_delegation(
                    connection,
                    research_runtime,
                    activity_store,
                    thread_id,
                    delegation_id,
                    question,
                    lambda: closed,
                )
            else:
                await _handle_delegation(
                    connection, agent_app, thread_id, delegation_id, question
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("voice delegation failed (session=%s)", session_id)
            if is_research:
                activity_store.set_phase(thread_id, "error", error=True)
                activity_store.append_event(
                    thread_id,
                    run_id=session_id,
                    kind="run_error",
                    message="Voice processing failed",
                )
            if not closed:
                await connection.session.commentary.append(
                    delegation_id=delegation_id,
                    content="Voice processing failed. Please try again.",
                )

    try:
        async with _client.live.sideband.connect(session_id=session_id) as connection:
            if is_research:
                activity_store.set_phase(thread_id, "listening")
                greeting = RESEARCH_GREETING
            else:
                greeting = GREETING
            # Bypass the graph for the greeting: it is transport setup, not a
            # research turn, and must never contend with the checkpoint.
            await connection.session.commentary.append(
                delegation_id=None, content=greeting
            )
            if not is_research:
                transcript_store.append(thread_id, "assistant", greeting)

            async for event in connection:
                if event.type == "session.input_transcript.delta":
                    transcript_buffer += event.delta
                elif event.type == "session.delegation.created":
                    question = transcript_buffer.strip()
                    transcript_buffer = ""
                    _trace(
                        f"delegation.created id={event.delegation.id} question={question!r}"
                    )
                    if not question:
                        continue
                    if active_delegation is not None and not active_delegation.done():
                        logger.warning(
                            "ignoring overlapping voice delegation session=%s", session_id
                        )
                        continue
                    if not is_research:
                        transcript_store.append(thread_id, "user", question)
                    active_delegation = asyncio.create_task(
                        handle(connection, event.delegation.id, question)
                    )
                    active_delegation.add_done_callback(_consume_task)
                elif event.type == "session.output_audio.delta" and is_research:
                    activity_store.set_phase(thread_id, "speaking")
                    if speaking_reset is not None:
                        speaking_reset.cancel()
                    speaking_reset = asyncio.create_task(
                        _restore_research_phase(activity_store, thread_id)
                    )
                    speaking_reset.add_done_callback(_consume_task)
                elif event.type == "error":
                    logger.warning(
                        "GPT-Live sideband error (session=%s): %s", session_id, event
                    )
                elif event.type == "session.closed":
                    closed = True
                    _trace(
                        f"session closed session_id={session_id} reason={event.reason}"
                    )
                    if active_delegation is not None and not active_delegation.done():
                        active_delegation.cancel()
                        with suppress(asyncio.CancelledError, TimeoutError):
                            await asyncio.wait_for(active_delegation, timeout=1.0)
                    break
    except Exception as exc:
        worker_error = exc
        logger.exception("voice worker failed (session=%s)", session_id)
    finally:
        closed = True
        for task in (active_delegation, speaking_reset):
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(task, timeout=1.0)
        if is_research:
            activity_store.end_session(thread_id, error=worker_error)
            await turn_coordinator.release(lease)
    _trace(f"worker exiting session_id={session_id}")
