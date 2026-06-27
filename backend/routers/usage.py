"""Usage tracking routes: aggregate API cost and token counts."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services.usage_service import get_usage_history, get_usage_today

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/today")
async def today_usage(db: AsyncSession = Depends(get_db)):
    """Return today's API usage grouped by provider, with daily and monthly totals."""
    return await get_usage_today(db)


@router.get("/history")
async def usage_history(
    timeframe: str = Query("weekly", pattern="^(daily|weekly|monthly|yearly)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return usage grouped by timeframe for the analytics charts.

    daily: last 24 hours in 4-hour blocks · weekly: last 7 days ·
    monthly: last 4 weeks · yearly: last 12 months.
    """
    return await get_usage_history(db, timeframe)
