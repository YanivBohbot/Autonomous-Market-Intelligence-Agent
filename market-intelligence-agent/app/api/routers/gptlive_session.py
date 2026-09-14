"""Bootstraps a GPT-Live voice session.

Proxies the browser's WebRTC SDP offer to OpenAI using our own API key (kept
server-side — the browser never sees it), then spawns the background
delegation worker that bridges the session to the LangGraph voice workflow.
"""
import asyncio
import logging

from fastapi import APIRouter, Request
from openai import AsyncOpenAI

from app.api.models.models import (
    GptLiveSessionRequest,
    GptLiveSessionResponse,
    VoiceTranscriptResponse,
)
from app.core.config import settings
from app.voice import transcript_store
from app.voice.hitl import is_interrupted
from app.voice.session import VOICE_INSTRUCTIONS
from app.voice.worker import run_delegation_worker

logger = logging.getLogger(__name__)
router = APIRouter()

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Hold references so the delegation tasks aren't garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


@router.post("/gptlive/session", response_model=GptLiveSessionResponse)
async def create_session(payload: GptLiveSessionRequest, request: Request) -> GptLiveSessionResponse:
    response = await _client.live.create(
        session={
            "model": settings.OPENAI_LIVE_MODEL,
            "delegation": {"type": "client"},
            "instructions": VOICE_INSTRUCTIONS,
            "audio": {"output": {"voice": settings.OPENAI_LIVE_VOICE}},
        },
        transport={"sdp": payload.sdp, "type": "webrtc"},
    )
    session_id = response.session.id
    thread_id = payload.thread_id or f"voice-{session_id}"
    agent_app = request.app.state.voice_agent_app

    task = asyncio.create_task(run_delegation_worker(session_id, thread_id, agent_app))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return GptLiveSessionResponse(session_id=session_id, sdp=response.transport.sdp)


@router.get("/voice/{thread_id}/transcript", response_model=VoiceTranscriptResponse)
async def get_voice_transcript(
    thread_id: str, request: Request, after: int = 0
) -> VoiceTranscriptResponse:
    entries = transcript_store.get_after(thread_id, after)
    last_id = entries[-1]["id"] if entries else after
    agent_app = request.app.state.voice_agent_app
    paused, action = await is_interrupted(agent_app, thread_id)
    return VoiceTranscriptResponse(
        messages=entries, last_id=last_id, paused=paused, action=action
    )
