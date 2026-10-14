"""Research conversation history: list / search / rename / delete.

Deterministic (no LLM). The index lives in the LangGraph store
("conversations",), the messages in the checkpointer; both come from
app.state, set in the server lifespan."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from app.agent.memory.conversations import (
    delete_conversation,
    is_research_thread,
    list_conversations,
    rename_conversation,
)

router = APIRouter()


class RenameRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 80:
            raise ValueError("title must be 1-80 characters")
        return v


@router.get("/conversations")
async def get_conversations(request: Request, q: str | None = None, limit: int = 50) -> list[dict]:
    return await list_conversations(request.app.state.store, q, max(1, min(limit, 200)))


@router.patch("/conversations/{thread_id}")
async def patch_conversation(thread_id: str, body: RenameRequest, request: Request) -> dict:
    row = await rename_conversation(request.app.state.store, thread_id, body.title)
    if row is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return row


@router.delete("/conversations/{thread_id}", status_code=204)
async def remove_conversation(thread_id: str, request: Request) -> Response:
    if not is_research_thread(thread_id):
        raise HTTPException(status_code=400, detail="only Research conversations can be deleted")
    await delete_conversation(request.app.state.store, request.app.state.checkpointer, thread_id)
    return Response(status_code=204)
