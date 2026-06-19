"""Settings routes: read all preferences and upsert one at a time."""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    """A single key/value setting change."""

    key: str
    value: str


@router.get("")
async def get_settings_endpoint(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Return all settings as a key/value object."""
    return await settings_service.get_all(db)


@router.patch("")
async def update_setting(payload: SettingUpdate, db: AsyncSession = Depends(get_db)):
    """Upsert one setting and echo back the full settings object."""
    await settings_service.set_value(db, payload.key, payload.value)
    return await settings_service.get_all(db)
