"""LiveKit Agents worker. Run with:

    uv run python -m app.voice.worker dev

For production-style worker (multi-room):

    uv run python -m app.voice.worker start
"""
import logging

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import JobContext

from app.voice.session import MarketIntelAssistant, build_voice_session

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice.worker")


async def entrypoint(ctx: JobContext) -> None:
    logger.info("voice session starting for room=%s", ctx.room.name)
    session = build_voice_session()
    await session.start(agent=MarketIntelAssistant(), room=ctx.room)
    await ctx.connect()
    await session.generate_reply(
        instructions="Greet the user briefly and ask what they want to know."
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
