"""Bootstraps a GPT-Live voice session.

Proxies the browser's WebRTC SDP offer to OpenAI using our own API key (kept
server-side — the browser never sees it), then spawns the background
delegation worker that bridges the session to the LangGraph voice workflow.
"""
import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from openai import AsyncOpenAI

from app.api.models.models import (
    GptLiveSessionRequest,
    GptLiveSessionResponse,
    VoiceDecisionRequest,
    VoiceDecisionResponse,
    VoiceStateResponse,
    VoiceTranscriptResponse,
)
from app.api.routers._helpers import pending_interrupt_from_snapshot
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


def _spawn_task(coroutine):
    return asyncio.create_task(coroutine)


def _allowed_origins() -> set[str]:
    return {
        origin.strip()
        for origin in settings.VOICE_ALLOWED_ORIGINS.split(",")
        if origin.strip()
    }


@router.post("/gptlive/session", response_model=GptLiveSessionResponse)
async def create_session(payload: GptLiveSessionRequest, request: Request) -> GptLiveSessionResponse:
    origin = request.headers.get("origin")
    if origin and origin not in _allowed_origins():
        raise HTTPException(status_code=403, detail="Voice origin is not allowed.")

    is_research = payload.surface == "research"
    coordinator = None
    activity_store = None
    research_runtime = None
    lease = None
    research_thread_id = payload.thread_id or f"voice-{uuid4()}"

    if is_research:
        coordinator = request.app.state.turn_coordinator
        activity_store = request.app.state.voice_activity_store
        research_runtime = request.app.state.research_voice_runtime
        lease = await coordinator.try_acquire(
            research_thread_id, f"voice:{uuid4()}"
        )
        if lease is None:
            raise HTTPException(
                status_code=409,
                detail="Another turn is active for this thread.",
            )
        activity_store.begin_session(research_thread_id)
        try:
            snapshot = await request.app.state.agent_app.aget_state(
                {
                    "configurable": {
                        "thread_id": research_thread_id,
                        "actor_id": "mia-agent",
                    }
                },
                subgraphs=True,
            )
            if pending_interrupt_from_snapshot(snapshot) is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Resolve the pending approval before starting voice mode.",
                )
        except Exception as exc:
            activity_store.end_session(research_thread_id, error=exc)
            await coordinator.release(lease)
            raise

    try:
        response = await _client.live.create(
            session={
                "model": settings.OPENAI_LIVE_MODEL,
                "delegation": {"type": "client"},
                "instructions": VOICE_INSTRUCTIONS,
                "audio": {"output": {"voice": settings.OPENAI_LIVE_VOICE}},
            },
            transport={"sdp": payload.sdp, "type": "webrtc"},
        )
    except Exception as exc:
        if lease is not None:
            activity_store.end_session(research_thread_id, error=exc)
            await coordinator.release(lease)
        raise

    session_id = response.session.id
    thread_id = research_thread_id if is_research else (
        payload.thread_id or f"voice-{session_id}"
    )
    agent_app = (
        request.app.state.agent_app
        if is_research
        else request.app.state.voice_agent_app
    )

    worker_coro = run_delegation_worker(
        session_id,
        thread_id,
        agent_app,
        surface=payload.surface,
        research_runtime=research_runtime,
        activity_store=activity_store,
        lease=lease,
        turn_coordinator=coordinator,
    )
    try:
        task = _spawn_task(worker_coro)
    except Exception as exc:
        worker_coro.close()
        if lease is not None:
            activity_store.end_session(thread_id, error=exc)
            await coordinator.release(lease)
        raise
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return GptLiveSessionResponse(session_id=session_id, sdp=response.transport.sdp)


@router.get("/voice/{thread_id}/state", response_model=VoiceStateResponse)
async def get_voice_state(
    thread_id: str, request: Request, after: int = 0
) -> VoiceStateResponse:
    snapshot = request.app.state.voice_activity_store.snapshot(
        thread_id, after=max(0, after)
    )
    return VoiceStateResponse.model_validate(snapshot)


@router.post(
    "/voice/{thread_id}/decision", response_model=VoiceDecisionResponse
)
async def decide_voice_action(
    thread_id: str, payload: VoiceDecisionRequest, request: Request
) -> VoiceDecisionResponse:
    result = await request.app.state.research_voice_runtime.resolve(
        thread_id, payload.interrupt_id, payload.decisions
    )
    if result.status == "stale":
        raise HTTPException(status_code=409, detail=result.response)
    if result.status == "error":
        raise HTTPException(status_code=500, detail=result.response)
    return VoiceDecisionResponse(status=result.status, response=result.response)


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
