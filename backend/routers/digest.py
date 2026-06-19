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
    cached: bool = False
    updated_at: str | None = None


@router.get("/today", response_model=DigestResponse)
async def today(db: AsyncSession = Depends(get_db)):
    """Return today's digest, serving the DB cache when available.

    The cache is populated on the first request of the day or after an explicit
    POST /digest/refresh. This avoids re-running costly API calls (news, stocks,
    Claude assembly) every time the Brief panel is opened.
    """
    cached = await digest_service.get_cached_digest(db)
    if cached:
        return DigestResponse(**cached)

    try:
        digest = await digest_service.build_digest(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Digest build failed")
        raise HTTPException(status_code=502, detail=f"Digest failed: {exc}") from exc

    await digest_service.save_digest_cache(db, digest)
    digest["cached"] = False
    digest["updated_at"] = None
    return DigestResponse(**digest)


@router.post("/refresh", response_model=DigestResponse)
async def refresh(db: AsyncSession = Depends(get_db)):
    """Force-rebuild today's digest and overwrite the cache.

    Called only when the user explicitly clicks Refresh in the Brief panel.
    """
    try:
        digest = await digest_service.build_digest(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Digest refresh failed")
        raise HTTPException(status_code=502, detail=f"Digest refresh failed: {exc}") from exc

    await digest_service.save_digest_cache(db, digest)
    digest["cached"] = False
    digest["updated_at"] = None
    return DigestResponse(**digest)
