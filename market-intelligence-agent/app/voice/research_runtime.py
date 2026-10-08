import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command, StateSnapshot

from app.api.routers._helpers import pending_interrupt_from_snapshot
from app.voice.activity_store import VoiceActivityStore

logger = logging.getLogger(__name__)

_SPECIALIST_NODES = {
    "rag_agent",
    "finance_agent",
    "portfolio_agent",
    "browser_agent",
    "memory_agent",
    "filesystem_agent",
    "email_agent",
}
_SAFE_FAILURE = "Voice processing failed"


@dataclass(frozen=True)
class VoiceTurnResult:
    status: Literal["completed", "approval_required", "error"]
    response: str
    run_id: str
    interrupt_id: str | None = None


@dataclass(frozen=True)
class VoiceDecisionResult:
    status: Literal["applied", "already_applied", "stale", "error"]
    response: str
    interrupt_id: str


class HitlDecisionCoordinator:
    """Apply at most one resume command for each stable interrupt id."""

    def __init__(self, activity_store: VoiceActivityStore) -> None:
        self._activity_store = activity_store
        self._locks: dict[str, asyncio.Lock] = {}
        self._results: dict[tuple[str, str], VoiceDecisionResult] = {}

    async def resolve(
        self,
        thread_id: str,
        interrupt_id: str,
        resume: Callable[[], Awaitable[VoiceDecisionResult]],
    ) -> VoiceDecisionResult:
        lock = self._locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            key = (thread_id, interrupt_id)
            previous = self._results.get(key)
            if previous is not None:
                return replace(previous, status="already_applied")

            pending = self._activity_store.snapshot(thread_id)["pending"]
            if not pending or pending.get("interrupt_id") != interrupt_id:
                return VoiceDecisionResult(
                    status="stale",
                    response="Approval is no longer pending.",
                    interrupt_id=interrupt_id,
                )

            result = await resume()
            self._results[key] = result
            current = self._activity_store.snapshot(thread_id)["pending"]
            if current and current.get("interrupt_id") == interrupt_id:
                self._activity_store.set_pending(thread_id, None)
            return result


class ResearchVoiceRuntime:
    def __init__(
        self,
        graph,
        activity_store: VoiceActivityStore,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.graph = graph
        self.activity_store = activity_store
        self._clock = clock
        self._decisions = HitlDecisionCoordinator(activity_store)

    async def run_turn(self, thread_id: str, question: str) -> VoiceTurnResult:
        run_id = str(uuid4())
        config = self._config(thread_id)
        seen_specialists: set[str] = set()
        started_tools: dict[str, tuple[str | None, float]] = {}
        finished_tools: set[str] = set()
        self.activity_store.set_phase(thread_id, "analyzing")

        try:
            async for namespace, mode, chunk in self.graph.astream(
                {"question": question},
                config,
                stream_mode=["updates"],
                subgraphs=True,
            ):
                if mode != "updates" or not isinstance(chunk, dict):
                    continue
                self._record_updates(
                    thread_id,
                    run_id,
                    namespace,
                    chunk,
                    seen_specialists,
                    started_tools,
                    finished_tools,
                )

            snapshot = await self.graph.aget_state(config, subgraphs=True)
            pending = pending_interrupt_from_snapshot(snapshot)
            if pending is not None:
                payload = _pending_payload(pending.interrupt_id, pending.value)
                self.activity_store.set_pending(thread_id, payload)
                self.activity_store.set_phase(thread_id, "approval_required")
                self.activity_store.append_event(
                    thread_id,
                    run_id=run_id,
                    kind="approval_required",
                    name=_first_action_name(payload),
                    message="Approval required",
                )
                return VoiceTurnResult(
                    status="approval_required",
                    response=_approval_prompt(payload),
                    run_id=run_id,
                    interrupt_id=pending.interrupt_id,
                )

            self.activity_store.set_pending(thread_id, None)
            response = _last_plain_ai_text(snapshot) or "Research complete."
            self.activity_store.append_event(
                thread_id,
                run_id=run_id,
                kind="run_finished",
                message="Research complete",
            )
            return VoiceTurnResult(
                status="completed",
                response=response,
                run_id=run_id,
            )
        except Exception:
            logger.exception("Research voice turn failed for thread %s", thread_id)
            self.activity_store.set_phase(thread_id, "error", error=True)
            self.activity_store.append_event(
                thread_id,
                run_id=run_id,
                kind="run_error",
                message=_SAFE_FAILURE,
            )
            return VoiceTurnResult(
                status="error",
                response=_SAFE_FAILURE,
                run_id=run_id,
            )

    async def resolve(
        self,
        thread_id: str,
        interrupt_id: str,
        decisions: list[dict],
    ) -> VoiceDecisionResult:
        async def resume() -> VoiceDecisionResult:
            run_id = str(uuid4())
            config = self._config(thread_id)
            self.activity_store.set_phase(thread_id, "analyzing")
            final_state = await self.graph.ainvoke(
                Command(resume={"decisions": decisions}),
                config,
            )
            snapshot = await self.graph.aget_state(config, subgraphs=True)
            pending = pending_interrupt_from_snapshot(snapshot)
            if pending is not None:
                payload = _pending_payload(pending.interrupt_id, pending.value)
                self.activity_store.set_pending(thread_id, payload)
                self.activity_store.set_phase(thread_id, "approval_required")
                self.activity_store.append_event(
                    thread_id,
                    run_id=run_id,
                    kind="approval_required",
                    name=_first_action_name(payload),
                    message="Approval required",
                )
                response = _approval_prompt(payload)
            else:
                self.activity_store.set_phase(thread_id, "analyzing")
                response = (
                    _last_plain_ai_text(snapshot)
                    or _last_plain_ai_text(final_state)
                    or "Decision applied."
                )
                self.activity_store.append_event(
                    thread_id,
                    run_id=run_id,
                    kind="run_finished",
                    message="Research complete",
                )
            return VoiceDecisionResult(
                status="applied",
                response=response,
                interrupt_id=interrupt_id,
            )

        try:
            return await self._decisions.resolve(thread_id, interrupt_id, resume)
        except Exception:
            logger.exception(
                "Research voice decision failed for thread %s interrupt %s",
                thread_id,
                interrupt_id,
            )
            self.activity_store.set_phase(thread_id, "approval_required")
            self.activity_store.append_event(
                thread_id,
                run_id=str(uuid4()),
                kind="run_error",
                message=_SAFE_FAILURE,
            )
            return VoiceDecisionResult(
                status="error",
                response=_SAFE_FAILURE,
                interrupt_id=interrupt_id,
            )

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {
            "configurable": {"thread_id": thread_id, "actor_id": "mia-agent"},
            "metadata": {"input_source": "voice"},
        }

    def _record_updates(
        self,
        thread_id: str,
        run_id: str,
        namespace,
        chunk: dict,
        seen_specialists: set[str],
        started_tools: dict[str, tuple[str | None, float]],
        finished_tools: set[str],
    ) -> None:
        for node_name, update in chunk.items():
            if (
                not namespace
                and node_name in _SPECIALIST_NODES
                and node_name not in seen_specialists
            ):
                seen_specialists.add(node_name)
                self.activity_store.append_event(
                    thread_id,
                    run_id=run_id,
                    kind="specialist_started",
                    name=node_name,
                )

            messages = update.get("messages", []) if isinstance(update, dict) else []
            for message in messages:
                if isinstance(message, AIMessage):
                    for tool_call in getattr(message, "tool_calls", None) or []:
                        tool_call_id = tool_call.get("id")
                        if not tool_call_id or tool_call_id in started_tools:
                            continue
                        name = tool_call.get("name")
                        started_tools[tool_call_id] = (name, self._clock())
                        self.activity_store.append_event(
                            thread_id,
                            run_id=run_id,
                            kind="tool_started",
                            name=name,
                            tool_call_id=tool_call_id,
                        )
                elif isinstance(message, ToolMessage):
                    tool_call_id = message.tool_call_id
                    if not tool_call_id or tool_call_id in finished_tools:
                        continue
                    finished_tools.add(tool_call_id)
                    started = started_tools.get(tool_call_id)
                    name = message.name or (started[0] if started else None)
                    duration_ms = (
                        max(0, round((self._clock() - started[1]) * 1000))
                        if started is not None
                        else None
                    )
                    self.activity_store.append_event(
                        thread_id,
                        run_id=run_id,
                        kind="tool_finished",
                        name=name,
                        tool_call_id=tool_call_id,
                        duration_ms=duration_ms,
                    )


def _pending_payload(interrupt_id: str, value: dict) -> dict:
    action_requests = value.get("action_requests")
    review_configs = value.get("review_configs")
    return {
        "interrupt_id": interrupt_id,
        "action_requests": action_requests if isinstance(action_requests, list) else [],
        "review_configs": review_configs if isinstance(review_configs, list) else [],
    }


def _first_action_name(pending: dict) -> str | None:
    requests = pending.get("action_requests") or []
    first = requests[0] if requests else None
    return first.get("name") if isinstance(first, dict) else None


def _approval_prompt(pending: dict) -> str:
    name = _first_action_name(pending) or "this action"
    return f"Approval required for {name}. Say Approve or Reject."


def _last_plain_ai_text(state_or_snapshot) -> str:
    if isinstance(state_or_snapshot, StateSnapshot):
        snapshots = _snapshots(state_or_snapshot)
        message_lists = [
            (snapshot.values or {}).get("messages", []) for snapshot in snapshots
        ]
    elif isinstance(state_or_snapshot, dict):
        message_lists = [state_or_snapshot.get("messages", [])]
    else:
        return ""

    for messages in message_lists:
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not getattr(
                message, "tool_calls", None
            ):
                return _message_text(message.content)
    return ""


def _snapshots(snapshot: StateSnapshot):
    yield snapshot
    for task in snapshot.tasks or ():
        child = getattr(task, "state", None)
        if isinstance(child, StateSnapshot):
            yield from _snapshots(child)


def _message_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content or "")
