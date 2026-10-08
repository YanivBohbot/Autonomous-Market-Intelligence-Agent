from pydantic import BaseModel, Field
from typing import Any, Literal, Optional


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
    sdp: str = Field(min_length=1, max_length=200_000)
    thread_id: Optional[str] = None
    surface: Literal["classic", "research"] = "classic"


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


VoicePhase = Literal[
    "connecting",
    "listening",
    "analyzing",
    "speaking",
    "approval_required",
    "disconnected",
    "error",
]
VoiceActivityKind = Literal[
    "specialist_started",
    "tool_started",
    "tool_finished",
    "approval_required",
    "run_finished",
    "run_error",
]


class VoiceActivityEventResponse(BaseModel):
    sequence: int
    run_id: str
    kind: VoiceActivityKind
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    duration_ms: Optional[int] = Field(default=None, ge=0)
    message: Optional[str] = None


class VoicePendingApprovalResponse(BaseModel):
    interrupt_id: str
    action_requests: list[dict[str, Any]]
    review_configs: list[dict[str, Any]] = Field(default_factory=list)


class VoiceStateResponse(BaseModel):
    phase: VoicePhase
    sequence: int
    events: list[VoiceActivityEventResponse]
    pending: Optional[VoicePendingApprovalResponse] = None
    error: Optional[str] = None


class VoiceDecisionRequest(BaseModel):
    interrupt_id: str
    decisions: list[dict[str, Any]] = Field(min_length=1)


class VoiceDecisionResponse(BaseModel):
    status: Literal["applied", "already_applied", "stale"]
    response: Optional[str] = None
