import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.agent.turn_coordinator import ThreadTurnCoordinator
from app.api.routers import gptlive_session
from app.api.server import app
from app.voice.activity_store import VoiceActivityStore
from app.voice.research_runtime import VoiceDecisionResult
from app.voice.worker import run_delegation_worker


class EmptyGraph:
    async def aget_state(self, config, subgraphs=False):
        assert subgraphs is True
        return SimpleNamespace(interrupts=(), tasks=(), values={})


class PendingGraph:
    async def aget_state(self, config, subgraphs=False):
        return SimpleNamespace(
            interrupts=(
                SimpleNamespace(
                    id="pending-1",
                    value={"action_requests": [{"name": "send_email", "args": {}}]},
                ),
            ),
            tasks=(),
            values={},
        )


class RuntimeStub:
    def __init__(self, result=None):
        self.result = result or VoiceDecisionResult(
            status="applied",
            response="Decision applied.",
            interrupt_id="interrupt-1",
        )
        self.calls = []

    async def resolve(self, thread_id, interrupt_id, decisions):
        self.calls.append((thread_id, interrupt_id, decisions))
        return self.result


class DummyTask:
    def __init__(self, coroutine):
        self.coroutine = coroutine
        self.coroutine.close()

    def add_done_callback(self, callback):
        callback(self)


@pytest.fixture
def voice_api(monkeypatch):
    captured = {}
    app.state.turn_coordinator = ThreadTurnCoordinator()
    app.state.voice_activity_store = VoiceActivityStore()
    app.state.agent_app = EmptyGraph()
    app.state.voice_agent_app = object()
    app.state.research_voice_runtime = RuntimeStub()
    monkeypatch.setattr(
        gptlive_session.settings,
        "VOICE_ALLOWED_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    )
    create = AsyncMock(
        return_value=SimpleNamespace(
            session=SimpleNamespace(id="live-session-1"),
            transport=SimpleNamespace(sdp="answer-sdp"),
        )
    )
    monkeypatch.setattr(gptlive_session._client.live, "create", create)

    def fake_worker(*args, **kwargs):
        captured["worker"] = (args, kwargs)

        async def complete():
            return None

        return complete()

    monkeypatch.setattr(gptlive_session, "run_delegation_worker", fake_worker)
    monkeypatch.setattr(
        gptlive_session,
        "_spawn_task",
        lambda coroutine: DummyTask(coroutine),
        raising=False,
    )
    yield TestClient(app, raise_server_exceptions=False), create, captured


def test_omitted_surface_preserves_classic_worker_contract(voice_api):
    client, create, captured = voice_api

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer-sdp", "thread_id": "classic-thread"},
    )

    assert response.status_code == 200
    assert response.json() == {"session_id": "live-session-1", "sdp": "answer-sdp"}
    args, kwargs = captured["worker"]
    assert args[:3] == ("live-session-1", "classic-thread", app.state.voice_agent_app)
    assert kwargs["surface"] == "classic"
    assert kwargs["research_runtime"] is None
    create.assert_awaited_once()


def test_research_session_acquires_lease_and_passes_shared_dependencies(voice_api):
    client, _, captured = voice_api

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer-sdp", "thread_id": "research-thread", "surface": "research"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    _, kwargs = captured["worker"]
    assert kwargs["surface"] == "research"
    assert kwargs["research_runtime"] is app.state.research_voice_runtime
    assert kwargs["activity_store"] is app.state.voice_activity_store
    assert kwargs["lease"].thread_id == "research-thread"
    assert kwargs["turn_coordinator"] is app.state.turn_coordinator
    assert asyncio.run(app.state.turn_coordinator.owner("research-thread")).startswith(
        "voice:"
    )
    asyncio.run(app.state.turn_coordinator.release(kwargs["lease"]))


def test_research_session_returns_409_before_openai_when_typed_turn_owns_thread(
    voice_api,
):
    client, create, _ = voice_api
    lease = asyncio.run(
        app.state.turn_coordinator.try_acquire("locked-thread", "text:run-1")
    )
    assert lease is not None
    try:
        response = client.post(
            "/gptlive/session",
            json={"sdp": "offer", "thread_id": "locked-thread", "surface": "research"},
        )
    finally:
        asyncio.run(app.state.turn_coordinator.release(lease))

    assert response.status_code == 409
    create.assert_not_awaited()


def test_research_session_rejects_existing_graph_interrupt_before_openai(voice_api):
    client, create, _ = voice_api
    app.state.agent_app = PendingGraph()

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer", "thread_id": "paused-thread", "surface": "research"},
    )

    assert response.status_code == 409
    create.assert_not_awaited()
    assert asyncio.run(app.state.turn_coordinator.owner("paused-thread")) is None


@pytest.mark.parametrize("sdp", ["", "x" * 200_001], ids=["empty", "oversized"])
def test_session_rejects_empty_or_oversized_sdp_before_openai(voice_api, sdp):
    client, create, _ = voice_api

    response = client.post("/gptlive/session", json={"sdp": sdp})

    assert response.status_code == 422
    create.assert_not_awaited()


def test_session_rejects_unlisted_browser_origin_before_openai(voice_api):
    client, create, _ = voice_api

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    create.assert_not_awaited()


def test_negotiation_failure_releases_research_lease(voice_api):
    client, create, _ = voice_api
    create.side_effect = RuntimeError("network failure")

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer", "thread_id": "failed-thread", "surface": "research"},
    )

    assert response.status_code == 500
    assert asyncio.run(app.state.turn_coordinator.owner("failed-thread")) is None


def test_worker_start_failure_releases_research_lease(voice_api, monkeypatch):
    client, _, _ = voice_api
    monkeypatch.setattr(
        gptlive_session,
        "_spawn_task",
        lambda coroutine: (_ for _ in ()).throw(RuntimeError("worker start failed")),
    )

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer", "thread_id": "worker-start-failed", "surface": "research"},
    )

    assert response.status_code == 500
    assert asyncio.run(
        app.state.turn_coordinator.owner("worker-start-failed")
    ) is None


def test_voice_state_endpoint_is_incremental_and_contains_no_transcript(voice_api):
    client, _, _ = voice_api
    store = app.state.voice_activity_store
    store.begin_session("state-thread")
    first = store.append_event(
        "state-thread", run_id="run-1", kind="specialist_started", name="rag_agent"
    )
    store.append_event(
        "state-thread", run_id="run-1", kind="run_finished", message="done"
    )

    response = client.get(
        "/voice/state-thread/state", params={"after": first["sequence"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert [event["kind"] for event in body["events"]] == ["run_finished"]
    assert "messages" not in body
    assert "transcript" not in body


def test_voice_decision_forwards_visual_edit_and_maps_result(voice_api):
    client, _, _ = voice_api
    runtime = app.state.research_voice_runtime
    decision = {
        "type": "edit",
        "edited_action": {
            "name": "send_email",
            "args": {"report_path": "reports/margaret.html"},
        },
    }

    response = client.post(
        "/voice/decision-thread/decision",
        json={"interrupt_id": "interrupt-1", "decisions": [decision]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "applied"
    assert runtime.calls == [("decision-thread", "interrupt-1", [decision])]


def test_voice_decision_maps_stale_interrupt_to_409(voice_api):
    client, _, _ = voice_api
    app.state.research_voice_runtime = RuntimeStub(
        VoiceDecisionResult(
            status="stale",
            response="Approval is no longer pending.",
            interrupt_id="stale",
        )
    )

    response = client.post(
        "/voice/decision-thread/decision",
        json={"interrupt_id": "stale", "decisions": [{"type": "approve"}]},
    )

    assert response.status_code == 409


class FakeCommentary:
    def __init__(self):
        self.calls = []

    async def append(self, **kwargs):
        self.calls.append(kwargs)


class FakeConnection:
    def __init__(self, events):
        self.events = events
        self.session = SimpleNamespace(commentary=FakeCommentary())

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def __aiter__(self):
        for event in self.events:
            if callable(event):
                event = await event()
            await asyncio.sleep(0)
            yield event


@pytest.mark.anyio
async def test_research_worker_does_not_write_transcripts_and_releases_lease(monkeypatch):
    from app.voice import transcript_store, worker

    thread_id = "research-worker-no-transcript"
    events = [
        SimpleNamespace(type="session.input_transcript.delta", delta="AAPL price"),
        SimpleNamespace(
            type="session.delegation.created",
            delegation=SimpleNamespace(id="delegation-1"),
        ),
        SimpleNamespace(type="session.closed", reason="client ended"),
    ]
    connection = FakeConnection(events)
    monkeypatch.setattr(
        worker._client.live.sideband,
        "connect",
        lambda session_id: connection,
    )
    runtime = SimpleNamespace(
        run_turn=AsyncMock(
            return_value=SimpleNamespace(status="completed", response="AAPL is $200.")
        ),
        resolve=AsyncMock(),
    )
    store = VoiceActivityStore()
    store.begin_session(thread_id)
    coordinator = ThreadTurnCoordinator()
    lease = await coordinator.try_acquire(thread_id, "voice:test")
    assert lease is not None

    await run_delegation_worker(
        "session-1",
        thread_id,
        object(),
        surface="research",
        research_runtime=runtime,
        activity_store=store,
        lease=lease,
        turn_coordinator=coordinator,
    )

    runtime.run_turn.assert_awaited_once_with(thread_id, "AAPL price")
    assert transcript_store.get_after(thread_id, 0) == []
    assert await coordinator.owner(thread_id) is None
    assert store.snapshot(thread_id)["phase"] == "disconnected"


@pytest.mark.anyio
async def test_session_close_during_analysis_cancels_task_and_releases_lease(monkeypatch):
    from app.voice import worker

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def analyze(thread_id, question):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def closed_after_analysis_started():
        await started.wait()
        return SimpleNamespace(type="session.closed", reason="client ended")

    connection = FakeConnection(
        [
            SimpleNamespace(type="session.input_transcript.delta", delta="research"),
            SimpleNamespace(
                type="session.delegation.created",
                delegation=SimpleNamespace(id="delegation-1"),
            ),
            closed_after_analysis_started,
        ]
    )
    monkeypatch.setattr(
        worker._client.live.sideband,
        "connect",
        lambda session_id: connection,
    )
    runtime = SimpleNamespace(run_turn=analyze, resolve=AsyncMock())
    store = VoiceActivityStore()
    store.begin_session("cancel-thread")
    coordinator = ThreadTurnCoordinator()
    lease = await coordinator.try_acquire("cancel-thread", "voice:test")
    assert lease is not None

    await run_delegation_worker(
        "session-1",
        "cancel-thread",
        object(),
        surface="research",
        research_runtime=runtime,
        activity_store=store,
        lease=lease,
        turn_coordinator=coordinator,
    )

    assert cancelled.is_set()
    assert await coordinator.owner("cancel-thread") is None


@pytest.mark.anyio
async def test_spoken_approval_uses_the_shared_decision_runtime(monkeypatch):
    from app.voice import worker

    connection = FakeConnection(
        [
            SimpleNamespace(type="session.input_transcript.delta", delta="approve"),
            SimpleNamespace(
                type="session.delegation.created",
                delegation=SimpleNamespace(id="delegation-1"),
            ),
            SimpleNamespace(type="session.closed", reason="client ended"),
        ]
    )
    monkeypatch.setattr(
        worker._client.live.sideband,
        "connect",
        lambda session_id: connection,
    )
    runtime = SimpleNamespace(
        run_turn=AsyncMock(),
        resolve=AsyncMock(
            return_value=SimpleNamespace(status="applied", response="Email sent once.")
        ),
    )
    store = VoiceActivityStore()
    store.begin_session("approval-thread")
    store.set_pending(
        "approval-thread",
        {
            "interrupt_id": "interrupt-1",
            "action_requests": [{"name": "send_email", "args": {}}],
            "review_configs": [],
        },
    )
    coordinator = ThreadTurnCoordinator()
    lease = await coordinator.try_acquire("approval-thread", "voice:test")

    await run_delegation_worker(
        "session-1",
        "approval-thread",
        object(),
        surface="research",
        research_runtime=runtime,
        activity_store=store,
        lease=lease,
        turn_coordinator=coordinator,
    )

    runtime.resolve.assert_awaited_once_with(
        "approval-thread", "interrupt-1", [{"type": "approve"}]
    )
    runtime.run_turn.assert_not_awaited()


@pytest.mark.anyio
async def test_worker_connection_failure_releases_research_lease(monkeypatch):
    from app.voice import worker

    class FailingConnection:
        async def __aenter__(self):
            raise RuntimeError("sideband failed")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        worker._client.live.sideband,
        "connect",
        lambda session_id: FailingConnection(),
    )
    store = VoiceActivityStore()
    store.begin_session("worker-failure")
    coordinator = ThreadTurnCoordinator()
    lease = await coordinator.try_acquire("worker-failure", "voice:test")

    await run_delegation_worker(
        "session-1",
        "worker-failure",
        object(),
        surface="research",
        research_runtime=SimpleNamespace(),
        activity_store=store,
        lease=lease,
        turn_coordinator=coordinator,
    )

    assert await coordinator.owner("worker-failure") is None
    snapshot = store.snapshot("worker-failure")
    assert snapshot["phase"] == "disconnected"
    assert snapshot["error"] == "Voice session disconnected"
