"""Voice session factory: builds the AgentSession with STT/LLM/TTS pipeline.

Task 4 swaps the placeholder openai.LLM for langchain.LLMAdapter(graph=agent_app).
"""
from livekit.agents import Agent, AgentSession
from livekit.plugins import deepgram, elevenlabs, silero
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


def build_voice_session() -> AgentSession:
    """Placeholder pipeline. Task 4 replaces the LLM with the LangGraph adapter."""
    from livekit.plugins import openai as lk_openai

    return AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-3", language="en-US", api_key=settings.DEEPGRAM_API_KEY
        ),
        llm=lk_openai.LLM(model="gpt-4o-mini", api_key=settings.OPENAI_API_KEY),
        tts=elevenlabs.TTS(
            model_id="eleven_flash_v2_5",
            voice_id=settings.ELEVENLABS_VOICE_ID,
            api_key=settings.ELEVENLABS_API_KEY,
        ),
        turn_detection=MultilingualModel(),
    )
