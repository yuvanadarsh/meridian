"""Google Calendar routes: sync and event queries."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import calendar_service, gmail_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])


async def _require_account(account_id: int, db: AsyncSession) -> None:
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")


@router.post("/sync/{account_id}")
async def sync(account_id: int, db: AsyncSession = Depends(get_db)):
    """Sync recent and upcoming events for an account."""
    await _require_account(account_id, db)
    try:
        return await calendar_service.sync_calendar(account_id, db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Calendar sync failed for account %s", account_id)
        raise HTTPException(status_code=500, detail=f"Calendar sync failed: {exc}") from exc


@router.get("/today/{account_id}")
async def today(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return today's events sorted by start time."""
    return await calendar_service.get_today(account_id, db)


@router.get("/upcoming/{account_id}")
async def upcoming(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return events for the next 7 days sorted by start time."""
    return await calendar_service.get_upcoming(account_id, db)
