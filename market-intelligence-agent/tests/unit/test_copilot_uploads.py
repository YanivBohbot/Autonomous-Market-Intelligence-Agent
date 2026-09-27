"""POST /copilot/uploads: lands a chat attachment on disk under
WORKSPACE_ROOT/uploads/ so the agent can read it back with the existing
read_text_file/list_directory tools. No GET route — only the agent reads it."""
import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.copilot import router
from app.core.config import settings


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_saves_the_file_under_uploads(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/copilot/uploads", files={"file": ("report.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")})
    assert resp.status_code == 200
    path = resp.json()["path"]
    assert path.startswith("uploads/") and path.endswith("_report.pdf")
    assert (tmp_path / path).read_bytes() == b"%PDF-1.4 fake"


def test_sanitizes_a_path_traversal_filename(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/copilot/uploads", files={"file": ("../../etc/passwd", io.BytesIO(b"x"), "text/plain")})
    assert resp.status_code == 200
    path = resp.json()["path"]
    assert ".." not in path
    saved = tmp_path / path
    assert saved.is_relative_to(tmp_path / "uploads")


def test_rejects_an_oversized_file(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("app.api.routers.copilot.MAX_UPLOAD_BYTES", 10)
    resp = client.post("/copilot/uploads", files={"file": ("big.txt", io.BytesIO(b"x" * 100), "text/plain")})
    assert resp.status_code == 413


def test_two_uploads_with_the_same_filename_do_not_collide(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    p1 = client.post("/copilot/uploads", files={"file": ("notes.txt", io.BytesIO(b"a"), "text/plain")}).json()["path"]
    p2 = client.post("/copilot/uploads", files={"file": ("notes.txt", io.BytesIO(b"b"), "text/plain")}).json()["path"]
    assert p1 != p2
    assert (tmp_path / p1).read_bytes() == b"a"
    assert (tmp_path / p2).read_bytes() == b"b"
