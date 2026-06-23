"""Voice routes: text-to-speech via ElevenLabs."""

import logging
import re

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from services import usage_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/voice", tags=["voice"])

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
# Low-latency model, well suited to a conversational assistant.
ELEVENLABS_MODEL = "eleven_turbo_v2_5"


def clean_for_tts(text: str) -> str:
    """Strip markdown, emojis, and URLs so spoken audio sounds natural.

    Responses are usually plain text already, but anything that leaks markdown
    (or an emoji) reads badly aloud — this normalizes it to clean prose.
    """
    # Code blocks and inline code first (before other rules touch their contents).
    text = re.sub(r"```[^`]*```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]+`", "", text)
    # Bold / italic markers.
    text = re.sub(r"\*+([^*]+)\*+", r"\1", text)
    # Headers and list markers at line starts.
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # URLs and non-ASCII (emojis, arrows, etc.).
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^\x00-\x7F]+", "", text)
    # Collapse whitespace.
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


class SpeakRequest(BaseModel):
    text: str


@router.post("/speak")
async def speak(payload: SpeakRequest, db: AsyncSession = Depends(get_db)) -> Response:
    """Synthesize speech for the given text and return it as audio/mpeg."""
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        raise HTTPException(
            status_code=500, detail="ElevenLabs API key or voice ID is not configured"
        )

    spoken_text = clean_for_tts(payload.text)
    if not spoken_text:
        raise HTTPException(status_code=400, detail="Nothing to speak after cleaning text")

    url = ELEVENLABS_TTS_URL.format(voice_id=settings.elevenlabs_voice_id)
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {
        "text": spoken_text,
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

    await usage_service.log_usage("elevenlabs", ELEVENLABS_MODEL, "characters", len(spoken_text), db)
    await db.commit()

    return Response(content=audio, media_type="audio/mpeg")
