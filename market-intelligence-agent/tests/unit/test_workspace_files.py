"""GET /workspace/files/{filename} -- serves reports generate_portfolio_report
+ write_file save into WORKSPACE_ROOT/reports, so the chat's download card
(ReportFileCard.tsx) has something to link to."""
from fastapi.testclient import TestClient

from app.core.config import settings


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", tmp_path)
    from fastapi import FastAPI

    from app.api.routers.workspace import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_serves_a_report_and_forces_download(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    (reports / "margaret-collins-portfolio-brief-2026-09-29.html").write_text("<html>brief</html>")

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/margaret-collins-portfolio-brief-2026-09-29.html")

    assert res.status_code == 200
    assert res.text == "<html>brief</html>"
    assert "attachment" in res.headers["content-disposition"]


def test_missing_file_returns_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/does-not-exist.html")
    assert res.status_code == 404


def test_path_traversal_is_blocked(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not leak me")
    (tmp_path / "reports").mkdir(parents=True)

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/..%2Fsecret.txt")
    assert res.status_code in (403, 404)
    assert b"do not leak me" not in res.content


def test_a_file_outside_reports_is_not_served(tmp_path, monkeypatch):
    # Only WORKSPACE_ROOT/reports is in scope -- a root-level file (like an
    # upload, or a plain filesystem_agent write) must not be reachable here.
    (tmp_path / "reports").mkdir(parents=True)
    (tmp_path / "notes.txt").write_text("not a report")

    client = _client(tmp_path, monkeypatch)
    res = client.get("/workspace/files/notes.txt")
    assert res.status_code == 404
