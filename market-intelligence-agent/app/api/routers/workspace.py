"""Serves files the agent's tools write into the workspace so a frontend can
display them — currently just browser_take_screenshot's PNGs, so the
Streamlit chat can render them inline instead of only narrating a path."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter(prefix="/workspace")


@router.get("/screenshots/{filename}")
async def get_screenshot(filename: str) -> FileResponse:
    # Path(...).name strips any directory components (including "..") the
    # same way app/mcp/browser/server.py's _screenshot_impl sanitizes the
    # filename it writes.
    safe_name = Path(filename).name
    root = Path(settings.WORKSPACE_ROOT)
    # The two browser backends disagree on where a screenshot actually
    # lands: app/mcp/browser/server.py (BROWSER_BACKEND=agentcore) always
    # writes under WORKSPACE_ROOT/screenshots. @playwright/mcp (local dev
    # default) ignores our --output-dir whenever the tool call supplies an
    # explicit filename and saves straight into WORKSPACE_ROOT instead —
    # confirmed live. Check both rather than trusting either backend's
    # documented behavior.
    for candidate in (root / "screenshots" / safe_name, root / safe_name):
        if candidate.is_file():
            return FileResponse(candidate, media_type="image/png")
    raise HTTPException(status_code=404, detail="Screenshot not found")
