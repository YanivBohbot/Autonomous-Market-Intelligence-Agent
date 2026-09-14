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
    # filename it writes — the two must agree on the on-disk layout.
    safe_name = Path(filename).name
    path = Path(settings.WORKSPACE_ROOT) / "screenshots" / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")
