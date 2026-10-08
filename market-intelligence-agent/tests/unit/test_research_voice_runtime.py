from collections.abc import Iterable

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Interrupt, PregelTask, StateSnapshot

from app.voice.activity_store import VoiceActivityStore
from app.voice.research_runtime import ResearchVoiceRuntime


def _snapshot(*, messages=(), tasks=(), interrupts=()) -> StateSnapshot:
    return StateSnapshot(
        values={"messages": list(messages)},
        next=(),
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=tuple(tasks),
        interrupts=tuple(interrupts),
    )


def _pending_snapshot(interrupt_id="interrupt-1") -> StateSnapshot:
    action = {
        "name": "send_email",
        "args": {"recipient": "client@example.com", "subject": "Report"},
    }
    child = _snapshot(
        messages=(
            AIMessage(
                content="",
                tool_calls=[{"id": "call-email", **action}],
            ),
        ),
        interrupts=(
            Interrupt(
                id=interrupt_id,
                value={
                    "action_requests": [action],
                    "review_configs": [
                        {
                            "action_name": "send_email",
                            "allowed_decisions": ["approve", "edit", "reject"],
                        }
                    ],
                },
            ),
        ),
    )
    return _snapshot(
        tasks=(PregelTask("task-1", "email_agent", ("email_agent",), state=child),)
    )


class FakeGraph:
    def __init__(
        self,
        *,
        stream_items: Iterable[tuple] = (),
        snapshots: Iterable[StateSnapshot] = (),
        final_state: dict | None = None,
        resume_error: Exception | None = None,
    ):
        self.stream_items = list(stream_items)
        self.snapshots = iter(snapshots)
        self.final_state = final_state or {"messages": [AIMessage(content="Resolved")]}
        self.resume_error = resume_error
        self.stream_config = None
        self.stream_input = None
        self.command = None
        self.invoke_calls = 0

    def astream(self, input_value, config, stream_mode, subgraphs=False):
        assert stream_mode == ["updates"]
        assert subgraphs is True
        self.stream_input = input_value
        self.stream_config = config

        async def generate():
            for item in self.stream_items:
                yield item

        return generate()

    async def aget_state(self, config, subgraphs=False):
        assert subgraphs is True
        return next(self.snapshots)

    async def ainvoke(self, command, config):
        self.invoke_calls += 1
        self.command = command
        if self.resume_error is not None:
            raise self.resume_error
        return self.final_state


@pytest.mark.anyio
async def test_run_turn_normalizes_specialist_and_tool_activity_and_returns_reply():
    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call-quote",
                "name": "yfinance_get_ticker_info",
                "args": {"ticker": "AAPL"},
            }
        ],
    )
    tool_result = ToolMessage(
        content="AAPL: 200",
        name="yfinance_get_ticker_info",
        tool_call_id="call-quote",
    )
    graph = FakeGraph(
        stream_items=[
            ((), "updates", {"finance_agent": {"messages": []}}),
            (("finance_agent:task",), "updates", {"model": {"messages": [tool_call]}}),
            (("finance_agent:task",), "updates", {"tools": {"messages": [tool_result]}}),
        ],
        snapshots=[_snapshot(messages=(AIMessage(content="AAPL is $200."),))],
    )
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    clock = iter([10.0, 10.125])
    runtime = ResearchVoiceRuntime(graph, store, clock=lambda: next(clock))

    result = await runtime.run_turn("thread-1", "What is AAPL trading at?")

    assert result.status == "completed"
    assert result.response == "AAPL is $200."
    assert graph.stream_input == {"question": "What is AAPL trading at?"}
    assert graph.stream_config["metadata"] == {"input_source": "voice"}
    snapshot = store.snapshot("thread-1")
    assert snapshot["phase"] == "analyzing"
    assert [event["kind"] for event in snapshot["events"]] == [
        "specialist_started",
        "tool_started",
        "tool_finished",
        "run_finished",
    ]
    assert snapshot["events"][2]["duration_ms"] == 125


@pytest.mark.anyio
async def test_run_turn_preserves_pending_interrupt_for_visual_and_spoken_approval():
    graph = FakeGraph(
        stream_items=[((), "updates", {"email_agent": {"messages": []}})],
        snapshots=[_pending_snapshot()],
    )
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    runtime = ResearchVoiceRuntime(graph, store)

    result = await runtime.run_turn("thread-1", "Email the report")

    assert result.status == "approval_required"
    snapshot = store.snapshot("thread-1")
    assert snapshot["phase"] == "approval_required"
    assert snapshot["pending"]["interrupt_id"] == "interrupt-1"
    assert snapshot["pending"]["action_requests"][0]["name"] == "send_email"
    assert snapshot["events"][-1]["kind"] == "approval_required"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "decision",
    [
        {"type": "approve"},
        {"type": "reject", "message": "Not now"},
    ],
)
async def test_resolve_applies_approve_or_reject(decision):
    graph = FakeGraph(
        snapshots=[_snapshot(messages=(AIMessage(content="Decision handled."),))]
    )
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    store.set_pending(
        "thread-1",
        {
            "interrupt_id": "interrupt-1",
            "action_requests": [{"name": "send_email", "args": {}}],
            "review_configs": [],
        },
    )
    runtime = ResearchVoiceRuntime(graph, store)

    result = await runtime.resolve("thread-1", "interrupt-1", [decision])

    assert result.status == "applied"
    assert result.response == "Decision handled."
    assert graph.command.resume == {"decisions": [decision]}
    assert store.snapshot("thread-1")["pending"] is None


@pytest.mark.anyio
async def test_first_decision_wins_when_visual_and_spoken_decisions_race():
    graph = FakeGraph(
        snapshots=[_snapshot(messages=(AIMessage(content="Sent once."),))]
    )
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    store.set_pending(
        "thread-1",
        {
            "interrupt_id": "interrupt-1",
            "action_requests": [{"name": "send_email", "args": {}}],
            "review_configs": [],
        },
    )
    runtime = ResearchVoiceRuntime(graph, store)

    first = await runtime.resolve(
        "thread-1", "interrupt-1", [{"type": "approve"}]
    )
    duplicate = await runtime.resolve(
        "thread-1", "interrupt-1", [{"type": "reject", "message": "late"}]
    )

    assert first.status == "applied"
    assert duplicate.status == "already_applied"
    assert duplicate.response == first.response
    assert graph.invoke_calls == 1


@pytest.mark.anyio
async def test_resume_failure_keeps_pending_approval_retryable():
    graph = FakeGraph(resume_error=RuntimeError("provider secret"))
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    pending = {
        "interrupt_id": "interrupt-1",
        "action_requests": [{"name": "send_email", "args": {}}],
        "review_configs": [],
    }
    store.set_pending("thread-1", pending)
    runtime = ResearchVoiceRuntime(graph, store)

    result = await runtime.resolve(
        "thread-1", "interrupt-1", [{"type": "approve"}]
    )

    assert result.status == "error"
    assert result.response == "Voice processing failed"
    assert store.snapshot("thread-1")["pending"] == pending
    assert graph.invoke_calls == 1


@pytest.mark.anyio
async def test_stale_interrupt_never_resumes_graph():
    graph = FakeGraph()
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    store.set_pending(
        "thread-1",
        {
            "interrupt_id": "current-interrupt",
            "action_requests": [{"name": "send_email", "args": {}}],
            "review_configs": [],
        },
    )
    runtime = ResearchVoiceRuntime(graph, store)

    result = await runtime.resolve(
        "thread-1", "stale-interrupt", [{"type": "approve"}]
    )

    assert result.status == "stale"
    assert graph.invoke_calls == 0
