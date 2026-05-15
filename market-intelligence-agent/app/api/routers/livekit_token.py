"""Mints short-lived LiveKit JWTs so the browser can join a voice room."""
import logging

from fastapi import APIRouter
from livekit import api

from app.api.models.models import LiveKitTokenRequest, LiveKitTokenResponse
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/livekit/token", response_model=LiveKitTokenResponse)
async def issue_token(payload: LiveKitTokenRequest) -> LiveKitTokenResponse:
    grants = api.VideoGrants(
        room_join=True,
        room=payload.room,
        can_publish=True,
        can_subscribe=True,
    )
    token = (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(payload.identity)
        .with_name(payload.identity)
        .with_grants(grants)
        .to_jwt()
    )
    return LiveKitTokenResponse(
        token=token,
        url=settings.LIVEKIT_URL,
        room=payload.room,
    )
