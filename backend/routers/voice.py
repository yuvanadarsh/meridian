"""Voice routes: text-to-speech via ElevenLabs."""

import logging

import aiohttp
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/voice", tags=["voice"])

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Low-latency model, well suited to a conversational assistant.
ELEVENLABS_MODEL = "eleven_turbo_v2_5"


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak")
async def speak(payload: SpeakRequest) -> Response:
    """Synthesize speech for the given text and return it as audio/mpeg."""
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        raise HTTPException(
            status_code=500, detail="ElevenLabs API key or voice ID is not configured"
        )

    url = ELEVENLABS_TTS_URL.format(voice_id=settings.elevenlabs_voice_id)
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {
        "text": payload.text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as response:
                if response.status != 200:
                    detail = (await response.text())[:200]
                    logger.error("ElevenLabs error %s: %s", response.status, detail)
                    raise HTTPException(
                        status_code=502,
                        detail=f"ElevenLabs error {response.status}: {detail}",
                    )
                audio = await response.read()
    except aiohttp.ClientError as exc:
        logger.exception("ElevenLabs request failed")
        raise HTTPException(status_code=502, detail=f"TTS request failed: {exc}") from exc

    return Response(content=audio, media_type="audio/mpeg")
