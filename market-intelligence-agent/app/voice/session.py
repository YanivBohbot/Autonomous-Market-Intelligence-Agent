"""Voice session factory: builds the AgentSession with STT/LLM/TTS pipeline.

The LLM is the compiled LangGraph workflow (via langchain.LLMAdapter), so
voice turns run the same RAG + grader + tools + HITL flow as text turns.
"""
import re
import uuid
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage

# Matches one or more leading `{"binary_score":"yes|no"}` JSON fragments that
# sometimes leak through when the LangGraph state has stale grader outputs.
# Without stripping, Deepgram TTS literally reads the JSON aloud.
_BINARY_SCORE_PREFIX = re.compile(r'^\s*(\{"binary_score":"\w+"\}\s*)+')
from livekit.agents import Agent, AgentSession, ChatContext, FlushSentinel, ModelSettings
from livekit.agents import llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.plugins import deepgram, langchain as lk_langchain, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from app.core.config import settings


class _StreamWithQuestion(lk_langchain.LangGraphStream):
    """Inject `question` (from the last HumanMessage) into the graph input.

    The market-intel `AgentState` declares `question: str` and the `rag` node
    reads `state["question"]`. `LLMAdapter` only converts chat_ctx → messages,
    so the graph would raise `KeyError('question')` on every voice turn.
    """

    def _chat_ctx_to_state(self) -> dict[str, Any]:
        state = super()._chat_ctx_to_state()
        question = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage) and msg.content:
                question = str(msg.content)
                break
        return {**state, "question": question}


class _LangGraphAdapter(lk_langchain.LLMAdapter):
    """`LLMAdapter` variant that emits `_StreamWithQuestion` so the market-intel
    LangGraph workflow receives the required `question` field."""

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **_):
        return _StreamWithQuestion(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            graph=self._graph,
            conn_options=conn_options,
            config=self._config,
            context=self._context,
            subgraphs=self._subgraphs,
            stream_mode=self._stream_mode,
        )


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

        # Quick filler so the user hears something within ~200ms instead of
        # waiting silently 3-5s for the LLM to finish.
        import sys
        print("[voice.session] yielding filler 'Let me check.'", file=sys.stderr, flush=True)
        yield llm.ChatChunk(
            id=str(uuid.uuid4()),
            delta=llm.ChoiceDelta(content="Let me check. ", role="assistant"),
        )
        yield FlushSentinel()

        # Strip leading `{"binary_score":"..."}` JSON blobs from the assistant
        # content stream. LLM tokens arrive one-by-one, so we buffer until we
        # either confirm the buffer is non-JSON or the regex matches a complete
        # set of JSON blobs followed by real content.
        prefix_done = False
        prefix_buffer = ""
        MAX_PREFIX_BUFFER = 200  # bail out after this many chars without resolving
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if prefix_done or not isinstance(chunk, llm.ChatChunk):
                yield chunk
                continue
            delta = chunk.delta
            if delta is None or not delta.content:
                yield chunk
                continue
            prefix_buffer += delta.content
            m = _BINARY_SCORE_PREFIX.match(prefix_buffer)
            if m is None:
                # Buffer has no JSON prefix at all — but might be building a
                # partial JSON like `{"binary_sc`. Detect that by checking if
                # the buffer is itself a valid prefix of the regex.
                if prefix_buffer.lstrip().startswith("{") and len(prefix_buffer) < MAX_PREFIX_BUFFER:
                    continue  # keep buffering
                # Buffer has no JSON, emit and stop checking
                chunk.delta.content = prefix_buffer
                prefix_done = True
                yield chunk
                continue
            if m.end() == len(prefix_buffer):
                # Buffer is entirely JSON blobs so far; keep accumulating
                if len(prefix_buffer) >= MAX_PREFIX_BUFFER:
                    # Give up; emit cleaned and stop
                    chunk.delta.content = ""
                    prefix_done = True
                    yield chunk
                continue
            # JSON prefix followed by real content — strip and emit the rest
            chunk.delta.content = prefix_buffer[m.end():]
            prefix_done = True
            print(
                f"[voice.session] stripped {m.end()} chars of binary_score JSON",
                file=sys.stderr, flush=True,
            )
            yield chunk


def build_voice_session(agent_app, thread_id: str) -> AgentSession:
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
            model="nova-3",
            language="en-US",
            api_key=settings.DEEPGRAM_API_KEY,
            # Wait longer for the user to finish a sentence before emitting a
            # final transcript. Default ~25ms over-segments natural pauses
            # into multiple turns, each of which cancels the in-flight LLM
            # generation and leaves the graph in a CancelledError state.
            endpointing_ms=600,
            # Nudge Deepgram toward stock tickers + market vocabulary so it
            # stops mishearing "Apple" as "April", "Tesla" as "Tessler", etc.
            keyterms=[
                "Apple", "Tesla", "Amazon", "Microsoft", "Google", "Meta",
                "Nvidia", "Netflix", "Alphabet", "Berkshire",
                "stock", "ticker", "price", "quarterly", "earnings", "revenue",
                "yfinance", "Pinecone",
            ],
        ),
        llm=_LangGraphAdapter(
            graph=agent_app,
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "actor_id": "mia-agent",
                }
            },
        ),
        # Deepgram Aura-2 instead of ElevenLabs: the supplied ElevenLabs API key
        # is on the free tier and returns HTTP 402 ("paid_plan_required") for
        # library voices, so no audio frames ever reached LiveKit. Deepgram TTS
        # uses the existing DEEPGRAM_API_KEY (already proven for STT) and has a
        # free tier.
        tts=deepgram.TTS(
            # Thalia: smoother, more conversational than Andromeda.
            model="aura-2-thalia-en",
            api_key=settings.DEEPGRAM_API_KEY,
        ),
        turn_detection=MultilingualModel(),
        tts_text_transforms=["filter_markdown", "filter_emoji"],
        # Preemptive generation races with our slow LangGraph pipeline (RAG +
        # grader + LLM + tools easily exceeds 1s), causing CancelledError mid-run.
        preemptive_generation=False,
    )
