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
