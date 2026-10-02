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

    safe_name = Path(filename).name
    root = Path(settings.WORKSPACE_ROOT)

    for candidate in (root / "screenshots" / safe_name, root / safe_name):
        if candidate.is_file():
            return FileResponse(candidate, media_type="image/png")
    raise HTTPException(status_code=404, detail="Screenshot not found")


@router.get("/files/{filename}")
async def get_report_file(filename: str) -> FileResponse:

    safe_name = Path(filename).name
    candidate = Path(settings.WORKSPACE_ROOT) / "reports" / safe_name
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(candidate, filename=safe_name)
