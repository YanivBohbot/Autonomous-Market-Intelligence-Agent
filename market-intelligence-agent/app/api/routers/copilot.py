"""Market Desk: AG-UI endpoint over the multi-agent graph (CopilotKit v2 talks
to it directly, no CopilotKit runtime).

The graph needs the app's checkpointer, which only exists inside lifespan, so
the agent is attached to app.state at startup (attach_market_desk) and this
handler mirrors ag_ui_langgraph.add_langgraph_fastapi_endpoint around it.
Included only when settings.COPILOT_ENABLED is true (see server.py).
"""
import logging
from pathlib import Path
from uuid import uuid4

from ag_ui.core import EventType, RunErrorEvent
from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from ag_ui_langgraph import LangGraphAgent
from fastapi import APIRouter, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore

from app.agent.multi_agent import build_multi_agent_app
from app.core.config import settings

MARKET_DESK_AGENT_NAME = "market_desk"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # matches the frontend's AttachmentsConfig.maxSize
# Each create_agent model turn crosses several middleware nodes, so a normal
# multi-tool answer overruns LangGraph's default of 25 steps. Model calls stay
# bounded by ModelCallLimitMiddleware and the supervisor's MAX_AGENT_HOPS.
RECURSION_LIMIT = 100

logger = logging.getLogger(__name__)

router = APIRouter()


def _is_summary(message) -> bool:
    return getattr(message, "additional_kwargs", {}).get("lc_source") == "summarization"


class MarketDeskAgent(LangGraphAgent):
    """LangGraphAgent that keeps SummarizationMiddleware's summary (a
    HumanMessage in state, needed by the model) out of what the browser
    renders — otherwise it shows up in the chat as if the user typed it.

    Hooks ag-ui-langgraph's snapshot filter (a private method, pinned by
    test_summary_message_is_not_sent_to_the_chat)."""

    def _filter_orphan_tool_messages(self, messages: list) -> list:
        return super()._filter_orphan_tool_messages([m for m in messages if not _is_summary(m)])

    def _build_command_from_agui_resume(self, entries: list, *, open_interrupts=None) -> Command:
        """CopilotKit's cancel() resumes with status "cancelled", but every
        interrupt here comes from HumanInTheLoopMiddleware, which needs
        {"decisions": [...]}: a cancel rejects each pending call instead of
        crashing the run and leaving the thread stuck."""
        if len(entries) == 1 and entries[0].status == "cancelled":
            count = _pending_action_count(open_interrupts or [], entries[0].interrupt_id)
            if count:
                return Command(resume={"decisions": [{"type": "reject", "message": "Cancelled by user."}] * count})
        return super()._build_command_from_agui_resume(entries, open_interrupts=open_interrupts)


def _pending_action_count(open_interrupts: list, interrupt_id: str) -> int:
    for item in open_interrupts:
        if getattr(item, "id", None) != interrupt_id:
            continue
        metadata = getattr(item, "metadata", None) or {}
        raw = (metadata.get("langgraph") or {}).get("raw") if isinstance(metadata, dict) else None
        requests = raw.get("action_requests") if isinstance(raw, dict) else None
        return len(requests) if isinstance(requests, list) else 0
    return 0


def build_market_desk_agent(
    checkpointer: BaseCheckpointSaver, store: BaseStore | None
) -> LangGraphAgent:
    return MarketDeskAgent(
        name=MARKET_DESK_AGENT_NAME,
        graph=build_multi_agent_app(checkpointer, store),
        emit_subagent_events=True,
        emit_interrupt_outcome=True,
        enable_legacy_on_interrupt_event=False,
        config={"recursion_limit": RECURSION_LIMIT},
    )


def attach_market_desk(
    app: FastAPI, checkpointer: BaseCheckpointSaver, store: BaseStore | None
) -> None:
    app.state.market_desk_agent = build_market_desk_agent(checkpointer, store)


@router.post("/copilot/market-desk")
async def market_desk(input_data: RunAgentInput, request: Request):
    agent: LangGraphAgent | None = getattr(request.app.state, "market_desk_agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="Market Desk agent is not ready.")

    encoder = EventEncoder(accept=request.headers.get("accept"))
    # LangGraphAgent keeps per-run state on the instance: one clone per request.
    run_agent = agent.clone()

    async def events():
        try:
            async for event in run_agent.run(input_data):
                yield encoder.encode(event)
        except Exception as exc:  # the headers are sent: report in-band
            logger.exception("Market Desk run failed (thread %s)", input_data.thread_id)
            yield encoder.encode(RunErrorEvent(type=EventType.RUN_ERROR, message=str(exc)))

    return StreamingResponse(events(), media_type=encoder.get_content_type())


@router.post("/copilot/uploads")
async def upload_to_workspace(file: UploadFile = File(...)) -> dict:
    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large.")
    safe_name = Path(file.filename or "upload").name  # strips ".." / directory components
    unique_name = f"{uuid4().hex[:8]}_{safe_name}"
    uploads_dir = Path(settings.WORKSPACE_ROOT) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / unique_name).write_bytes(body)
    return {"path": f"uploads/{unique_name}"}
