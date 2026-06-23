"""Usage tracking routes: aggregate API cost and token counts."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services.usage_service import get_usage_today

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/today")
async def today_usage(db: AsyncSession = Depends(get_db)):
    """Return today's API usage grouped by provider, with daily and monthly totals."""
    return await get_usage_today(db)
