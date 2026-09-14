from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.server import app
from app.voice import transcript_store

client = TestClient(app)


def test_append_and_get_after_returns_only_newer_entries():
    thread_id = "voice-test-thread-1"

    transcript_store.append(thread_id, "assistant", "hi there")
    first = transcript_store.get_after(thread_id, 0)
    assert len(first) == 1
    assert first[0]["role"] == "assistant"
    assert first[0]["content"] == "hi there"

    transcript_store.append(thread_id, "user", "what's AAPL doing")
    second = transcript_store.get_after(thread_id, first[0]["id"])
    assert len(second) == 1
    assert second[0]["role"] == "user"


def test_get_after_unknown_thread_returns_empty():
    assert transcript_store.get_after("voice-never-seen", 0) == []


def test_transcript_endpoint_returns_new_messages_and_advances_cursor():
    thread_id = "voice-test-thread-2"
    transcript_store.append(thread_id, "assistant", "Hi, I'm your market intelligence assistant.")

    mock_agent_app = MagicMock()
    app.state.voice_agent_app = mock_agent_app
    try:
        with patch(
            "app.api.routers.gptlive_session.is_interrupted",
            new=AsyncMock(return_value=(False, None)),
        ):
            res = client.get(f"/voice/{thread_id}/transcript", params={"after": 0})
        assert res.status_code == 200
        body = res.json()
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "assistant"
        last_id = body["last_id"]

        with patch(
            "app.api.routers.gptlive_session.is_interrupted",
            new=AsyncMock(return_value=(False, None)),
        ):
            res2 = client.get(f"/voice/{thread_id}/transcript", params={"after": last_id})
        assert res2.status_code == 200
        assert res2.json()["messages"] == []
        assert res2.json()["last_id"] == last_id
        # Verify the new fields are present
        assert "paused" in body
        assert "action" in body
    finally:
        # Clean up
        if hasattr(app.state, "voice_agent_app"):
            delattr(app.state, "voice_agent_app")


def test_transcript_endpoint_reports_paused_state():
    thread_id = "voice-test-thread-paused"

    mock_agent_app = MagicMock()
    app.state.voice_agent_app = mock_agent_app
    try:
        with patch(
            "app.api.routers.gptlive_session.is_interrupted",
            new=AsyncMock(return_value=(True, "send_email with args {'to': 'x@y.com'}")),
        ):
            res = client.get(f"/voice/{thread_id}/transcript", params={"after": 0})

        assert res.status_code == 200
        body = res.json()
        assert body["paused"] is True
        assert body["action"] == "send_email with args {'to': 'x@y.com'}"
    finally:
        # Clean up
        if hasattr(app.state, "voice_agent_app"):
            delattr(app.state, "voice_agent_app")


def test_transcript_endpoint_reports_not_paused():
    thread_id = "voice-test-thread-not-paused"

    mock_agent_app = MagicMock()
    app.state.voice_agent_app = mock_agent_app
    try:
        with patch(
            "app.api.routers.gptlive_session.is_interrupted",
            new=AsyncMock(return_value=(False, None)),
        ):
            res = client.get(f"/voice/{thread_id}/transcript", params={"after": 0})

        assert res.status_code == 200
        body = res.json()
        assert body["paused"] is False
        assert body["action"] is None
    finally:
        # Clean up
        if hasattr(app.state, "voice_agent_app"):
            delattr(app.state, "voice_agent_app")
