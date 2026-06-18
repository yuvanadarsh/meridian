"""Obsidian routes: append conversation exchanges to the daily note."""

import logging

from fastapi import APIRouter

from models.obsidian import AppendExchange
from services import obsidian_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/obsidian", tags=["obsidian"])


@router.post("/append")
async def append(payload: AppendExchange):
    """Append a conversation exchange to today's daily note (no-op if no vault)."""
    written = await obsidian_service.append_exchange(payload.user_message, payload.assistant_message)
    return {"written": written}
