# Modèles de données (Pydantic) pour valider les entrées/sorties
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    query: str
    thread_id: str = "default_thread"


class ChatResponse(BaseModel):
    response: str
    status: str  # "completed" ou "interrupted"
    next_step: Optional[str] = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
