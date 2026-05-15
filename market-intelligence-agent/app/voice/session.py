"""Voice session factory: builds the AgentSession with STT/LLM/TTS pipeline.

The LLM is the compiled LangGraph workflow (via langchain.LLMAdapter), so
voice turns run the same RAG + grader + tools + HITL flow as text turns.
"""
import uuid
from typing import AsyncGenerator

from livekit.agents import Agent, AgentSession, ChatContext, FlushSentinel, ModelSettings
from livekit.agents import llm
from livekit.plugins import deepgram, elevenlabs, langchain as lk_langchain, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from app.core.config import settings


VOICE_PREAMBLE = (
    "VOICE MODE. Keep every reply under 30 words. "
    "Never use markdown, bullet points, or numbered lists. "
    "Spell out numbers and acronyms. "
    "End with a brief question to keep the conversation flowing."
)


class MarketIntelAssistant(Agent):
    """Voice persona with verbal HITL support.

    When `agent_app` and `thread_id` are provided, `llm_node` detects pending
    LangGraph interrupts and either re-prompts for confirmation or resumes the
    graph with the user's verdict before delegating to the normal LLM path.
    """

    def __init__(self, agent_app=None, thread_id: str | None = None) -> None:
        chat_ctx = ChatContext()
        chat_ctx.add_message(role="system", content=VOICE_PREAMBLE)
        super().__init__(
            instructions=(
                "You are a market intelligence voice assistant. "
                "Keep replies under 30 words. Speak naturally, no bullet points, "
                "no markdown. Spell out numbers when reading them. "
                "If asked to send an email or save data, confirm verbally first."
            ),
            chat_ctx=chat_ctx,
        )
        self._agent_app = agent_app
        self._thread_id = thread_id

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[llm.ChatChunk | str | FlushSentinel, None]:
        from app.voice.hitl import classify_verdict, is_interrupted, resume_with

        if self._agent_app and self._thread_id:
            paused, action = await is_interrupted(self._agent_app, self._thread_id)
            if paused:
                last_user = next(
                    (m.content for m in reversed(chat_ctx.items) if m.role == "user"),
                    "",
                )
                verdict = classify_verdict(str(last_user))
                if verdict is None:
                    yield llm.ChatChunk(
                        id=str(uuid.uuid4()),
                        delta=llm.ChoiceDelta(
                            content=f"I need confirmation before {action}. Say yes or no.",
                            role="assistant",
                        ),
                    )
                    return
                # Resume the graph, then yield the final AI message as the spoken reply.
                state = await resume_with(self._agent_app, self._thread_id, verdict)
                for msg in reversed(state.get("messages", [])):
                    content = getattr(msg, "content", None)
                    if content and not getattr(msg, "tool_calls", None):
                        yield llm.ChatChunk(
                            id=str(uuid.uuid4()),
                            delta=llm.ChoiceDelta(content=str(content), role="assistant"),
                        )
                        return
                return  # No message to speak (e.g., after reject)

        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk


def build_voice_session(agent_app) -> AgentSession:
    """Wire the compiled LangGraph app in as the LLM.

    `agent_app` is the result of
    `app.agent.graph.build_agent_app(checkpointer, store)`.

    TTS text transforms strip markdown + emoji from the LLM output before
    it reaches ElevenLabs, so the synthesizer doesn't read literal
    asterisks or emoji names aloud.
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
        tts_text_transforms=["filter_markdown", "filter_emoji"],
        preemptive_generation=True,
    )
