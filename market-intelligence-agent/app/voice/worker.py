"""LiveKit Agents worker. Run with:

    uv run python -m app.voice.worker dev

For production-style worker (multi-room):

    uv run python -m app.voice.worker start
"""

import asyncio
import logging
import sys
import uuid

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import JobContext, RoomInputOptions

from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import create_store
from app.voice.graph import build_voice_agent_app
from app.voice.session import MarketIntelAssistant, build_voice_session

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice.worker")


def _trace(msg: str) -> None:
    """Print to stderr unconditionally so we can debug subprocess startup
    even if the standard logger gets reconfigured by livekit-agents."""
    print(f"[voice.worker] {msg}", file=sys.stderr, flush=True)


async def entrypoint(ctx: JobContext) -> None:
    _trace(f"entrypoint START room={ctx.room.name}")

    async with create_checkpointer() as checkpointer:
        _trace("checkpointer open, building graph")
        store = create_store()
        agent_app = build_voice_agent_app(checkpointer, store)
        # Unique per session so a cancelled / errored graph never poisons future
        # sessions in the same room. LiveKit reuses room names across reconnects.
        thread_id = f"voice-{ctx.room.name}-{uuid.uuid4().hex[:8]}"
        session = build_voice_session(agent_app, thread_id)
        _trace(f"session built, starting (thread_id={thread_id})")

        await ctx.connect()
        _trace("ctx.connect() done")

        await session.start(
            agent=MarketIntelAssistant(agent_app, thread_id),
            room=ctx.room,
            room_input_options=RoomInputOptions(close_on_disconnect=False),
        )
        _trace("session.start() done, sending greeting")

        # Use `say()` (direct TTS, bypasses LLM) instead of `generate_reply()` so
        # the greeting does not run the LangGraph workflow. The graph is slow
        # (RAG + grader + LLM), and if the user speaks during the greeting,
        # the in-flight graph execution gets cancelled mid-run and the
        # checkpointer is left in a `CancelledError` state that poisons every
        # subsequent turn.
        await session.say("Hi, I'm your market intelligence assistant. How can I help?")
        _trace("greeting sent, waiting for room disconnect")

        # Keep the entrypoint alive (and the checkpointer connection open) for the
        # whole room lifetime. Exit when either the room disconnects OR the last
        # remote participant leaves (so the agent doesn't linger in a now-empty
        # room and prevent LiveKit from dispatching a new worker on the next
        # Connect).
        disconnected = asyncio.Event()
        ctx.room.on("disconnected", lambda *_a, **_k: disconnected.set())
        ctx.room.on(
            "participant_disconnected",
            lambda *_a, **_k: disconnected.set() if len(ctx.room.remote_participants) == 0 else None,
        )
        if ctx.room.connection_state == rtc.ConnectionState.CONN_DISCONNECTED:
            disconnected.set()
        await disconnected.wait()
        _trace(f"entrypoint END room={ctx.room.name}")


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
