from app.api.models.models import VoiceDecisionRequest, VoiceStateResponse
from app.voice.activity_store import VoiceActivityStore


def test_begin_session_resets_ephemeral_state():
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    store.append_event(
        "thread-1",
        run_id="run-1",
        kind="specialist_started",
        name="finance_agent",
    )
    store.set_pending(
        "thread-1",
        {
            "interrupt_id": "interrupt-1",
            "action_requests": [{"name": "send_email", "args": {}}],
            "review_configs": [],
        },
    )

    store.begin_session("thread-1")

    assert store.snapshot("thread-1") == {
        "phase": "connecting",
        "sequence": 0,
        "events": [],
        "pending": None,
        "error": None,
    }


def test_events_are_monotonic_incremental_and_bounded_to_200():
    store = VoiceActivityStore()
    store.begin_session("thread-1")

    for index in range(205):
        store.append_event(
            "thread-1",
            run_id="run-1",
            kind="tool_started",
            name=f"tool-{index}",
            tool_call_id=f"call-{index}",
        )

    snapshot = store.snapshot("thread-1")
    assert snapshot["sequence"] == 205
    assert len(snapshot["events"]) == 200
    assert snapshot["events"][0]["sequence"] == 6
    assert snapshot["events"][-1]["sequence"] == 205

    incremental = store.snapshot("thread-1", after=202)
    assert [event["sequence"] for event in incremental["events"]] == [203, 204, 205]


def test_disconnect_preserves_unresolved_pending_approval():
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    pending = {
        "interrupt_id": "interrupt-1",
        "action_requests": [
            {"name": "send_email", "args": {"recipient": "client@example.com"}}
        ],
        "review_configs": [{"action_name": "send_email"}],
    }
    store.set_pending("thread-1", pending)

    store.end_session("thread-1")

    snapshot = store.snapshot("thread-1")
    assert snapshot["phase"] == "disconnected"
    assert snapshot["pending"] == pending


def test_error_state_and_events_never_echo_exception_details():
    store = VoiceActivityStore()
    store.begin_session("thread-1")

    store.set_phase(
        "thread-1",
        "error",
        error=RuntimeError("OPENAI_API_KEY=super-secret"),
    )
    event = store.append_event(
        "thread-1",
        run_id="run-1",
        kind="run_error",
        message="SMTP password super-secret",
    )

    assert store.snapshot("thread-1")["error"] == "Voice processing failed"
    assert event["message"] == "Voice processing failed"


def test_state_and_decision_models_match_store_contract():
    store = VoiceActivityStore()
    store.begin_session("thread-1")
    store.set_phase("thread-1", "listening")
    store.append_event(
        "thread-1",
        run_id="run-1",
        kind="tool_finished",
        name="web_search",
        tool_call_id="call-1",
        duration_ms=42,
    )

    response = VoiceStateResponse.model_validate(store.snapshot("thread-1"))
    decision = VoiceDecisionRequest(
        interrupt_id="interrupt-1",
        decisions=[{"type": "approve"}],
    )

    assert response.phase == "listening"
    assert response.events[0].duration_ms == 42
    assert decision.decisions == [{"type": "approve"}]
