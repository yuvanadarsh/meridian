"""Digest routes: assemble today's brief (calendar, email, news, stocks)."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import digest_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/digest", tags=["digest"])


class DigestResponse(BaseModel):
    """The four digest sections plus a voice-ready assembled brief."""

    calendar: str
    emails: str
    news: str
    stocks: str
    full_text: str


@router.get("/today", response_model=DigestResponse)
async def today(db: AsyncSession = Depends(get_db)):
    """Build and return today's full digest."""
    try:
        digest = await digest_service.build_digest(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Digest build failed")
        raise HTTPException(status_code=502, detail=f"Digest failed: {exc}") from exc
    return DigestResponse(**digest)
