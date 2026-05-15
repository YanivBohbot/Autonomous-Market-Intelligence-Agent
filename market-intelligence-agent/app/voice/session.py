"""Voice session factory: builds the AgentSession with STT/LLM/TTS pipeline.

The LLM is the compiled LangGraph workflow (via langchain.LLMAdapter), so
voice turns run the same RAG + grader + tools + HITL flow as text turns.
"""
from livekit.agents import Agent, AgentSession
from livekit.plugins import deepgram, elevenlabs, langchain as lk_langchain, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from app.core.config import settings


class MarketIntelAssistant(Agent):
    """Voice persona. Instructions stay short — verbal answers, no markdown."""

    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a market intelligence voice assistant. "
                "Keep replies under 30 words. Speak naturally, no bullet points, "
                "no markdown. Spell out numbers when reading them. "
                "If asked to send an email or save data, confirm verbally first."
            ),
        )


def build_voice_session(agent_app) -> AgentSession:
    """Wire the compiled LangGraph app in as the LLM.

    `agent_app` is the result of
    `app.agent.graph.build_agent_app(checkpointer, store)`.
    """
    return AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-3", language="en-US", api_key=settings.DEEPGRAM_API_KEY
        ),
        llm=lk_langchain.LLMAdapter(graph=agent_app),
        tts=elevenlabs.TTS(
            model="eleven_flash_v2_5",
            voice_id=settings.ELEVENLABS_VOICE_ID,
            api_key=settings.ELEVENLABS_API_KEY,
        ),
        turn_detection=MultilingualModel(),
        preemptive_generation=True,
    )
