from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    query: str
    thread_id: str = "default_thread"


class ChatResponse(BaseModel):
    response: str
    status: str
    next_step: Optional[str] = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
