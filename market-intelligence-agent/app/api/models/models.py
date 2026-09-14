from pydantic import BaseModel
from typing import Optional


class ChatResponse(BaseModel):
    response: str
    status: str
    next_step: Optional[str] = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool


class StreamRequest(BaseModel):
    query: str
    thread_id: str = "default_thread"


class HealthResponse(BaseModel):
    status: str
    version: str


class GptLiveSessionRequest(BaseModel):
    sdp: str
    thread_id: Optional[str] = None


class GptLiveSessionResponse(BaseModel):
    session_id: str
    sdp: str


class VoiceTranscriptEntry(BaseModel):
    id: int
    role: str
    content: str


class VoiceTranscriptResponse(BaseModel):
    messages: list[VoiceTranscriptEntry]
    last_id: int
    paused: bool
    action: Optional[str] = None
