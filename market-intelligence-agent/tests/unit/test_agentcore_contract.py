"""Smoke tests for the AgentCore Runtime contract endpoints (/ping, /invocations)."""

from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)


def test_ping_returns_healthy():
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "Healthy"}


def test_invocations_rejects_empty_payload():
    """Neither prompt nor resume → returns a clean error in the response body
    (200, not 422) so AgentCore Runtime treats it as a normal invocation."""
    response = client.post("/invocations", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "prompt or resume" in body["response"].lower()
    assert body["session_id"] == "default_thread"


def test_invocations_honors_session_header():
    """The X-Amzn-Bedrock-AgentCore-Runtime-Session-Id header should be
    threaded into the response when no session_id is in the body."""
    response = client.post(
        "/invocations",
        json={},
        headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": "abc-123"},
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == "abc-123"
