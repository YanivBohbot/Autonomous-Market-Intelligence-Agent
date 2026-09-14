"""Tests for POST /gptlive/session.

Focus: `create_session` must forward the caller-supplied `payload.thread_id`
into `run_delegation_worker` unchanged (Task 2 of the unified voice/text
thread plan — voice and text sharing one LangGraph thread depends entirely on
this forwarding actually happening), and must still fall back to
`voice-<session_id>` when no `thread_id` is supplied.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)


def _fake_live_create_response(session_id: str):
    """Stand-in for the AsyncOpenAI `client.live.create(...)` response."""
    return SimpleNamespace(
        session=SimpleNamespace(id=session_id),
        transport=SimpleNamespace(sdp="fake-answer-sdp"),
    )


def test_create_session_forwards_caller_supplied_thread_id():
    mock_agent_app = MagicMock()
    app.state.voice_agent_app = mock_agent_app
    try:
        with (
            patch(
                "app.api.routers.gptlive_session._client.live.create",
                new=AsyncMock(return_value=_fake_live_create_response("sess-abc")),
            ),
            patch(
                "app.api.routers.gptlive_session.run_delegation_worker",
                new=AsyncMock(),
            ) as mock_worker,
        ):
            response = client.post(
                "/gptlive/session",
                json={"sdp": "fake-offer-sdp", "thread_id": "web_session_test123"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "sess-abc"
        assert body["sdp"] == "fake-answer-sdp"

        mock_worker.assert_called_once_with("sess-abc", "web_session_test123", mock_agent_app)
    finally:
        if hasattr(app.state, "voice_agent_app"):
            delattr(app.state, "voice_agent_app")


def test_create_session_falls_back_to_voice_prefixed_thread_id_when_absent():
    mock_agent_app = MagicMock()
    app.state.voice_agent_app = mock_agent_app
    try:
        with (
            patch(
                "app.api.routers.gptlive_session._client.live.create",
                new=AsyncMock(return_value=_fake_live_create_response("sess-xyz")),
            ),
            patch(
                "app.api.routers.gptlive_session.run_delegation_worker",
                new=AsyncMock(),
            ) as mock_worker,
        ):
            response = client.post(
                "/gptlive/session",
                json={"sdp": "fake-offer-sdp"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["session_id"] == "sess-xyz"

        mock_worker.assert_called_once_with("sess-xyz", "voice-sess-xyz", mock_agent_app)
    finally:
        if hasattr(app.state, "voice_agent_app"):
            delattr(app.state, "voice_agent_app")
