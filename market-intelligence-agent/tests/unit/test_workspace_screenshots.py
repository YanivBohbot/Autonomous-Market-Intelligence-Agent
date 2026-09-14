"""GET /workspace/screenshots/{filename} — serves screenshots the agent's
browser_take_screenshot tool writes into WORKSPACE_ROOT/screenshots, so the
Streamlit chat can render them inline (app/ui/app.py)."""
from fastapi.testclient import TestClient

from app.core.config import settings


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", tmp_path)
    from app.api.routers.workspace import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_serves_existing_screenshot(tmp_path, monkeypatch):
    shots = tmp_path / "screenshots"
    shots.mkdir(parents=True)
    (shots / "evidence.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/screenshots/evidence.png")

    assert res.status_code == 200
    assert res.content == b"\x89PNG\r\n\x1a\nfake-png-bytes"
    assert res.headers["content-type"] == "image/png"


def test_serves_screenshot_saved_directly_under_workspace_root(tmp_path, monkeypatch):
    # @playwright/mcp (local dev backend) ignores our --output-dir when the
    # tool call supplies an explicit filename and saves straight into
    # WORKSPACE_ROOT instead of WORKSPACE_ROOT/screenshots — confirmed live
    # via the browser (data/workspace/example-com-screenshot.png, not
    # data/workspace/screenshots/example-com-screenshot.png). The endpoint
    # must still find it.
    (tmp_path / "screenshots").mkdir(parents=True)
    (tmp_path / "evidence.png").write_bytes(b"\x89PNG\r\n\x1a\nroot-level-bytes")

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/screenshots/evidence.png")

    assert res.status_code == 200
    assert res.content == b"\x89PNG\r\n\x1a\nroot-level-bytes"


def test_missing_screenshot_returns_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/screenshots/does-not-exist.png")
    assert res.status_code == 404


def test_path_traversal_is_blocked(tmp_path, monkeypatch):
    # A secret file living next to (not inside) the screenshots dir must
    # never be reachable through the endpoint.
    secret = tmp_path / "secret.txt"
    secret.write_text("do not leak me")
    (tmp_path / "screenshots").mkdir(parents=True)

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/screenshots/..%2Fsecret.txt")
    assert res.status_code in (403, 404)
    assert b"do not leak me" not in res.content
