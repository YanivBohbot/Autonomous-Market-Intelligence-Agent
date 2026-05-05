from importlib.metadata import version as _pkg_version, PackageNotFoundError
from fastapi import APIRouter
from app.api.models.models import HealthResponse

router = APIRouter()


def _get_version() -> str:
    try:
        return _pkg_version("market-intelligence-agent")
    except PackageNotFoundError:
        return "0.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return {"status": "ok", "version": _get_version()}
