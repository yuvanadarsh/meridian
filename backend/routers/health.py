"""Health check endpoint."""

import logging

from fastapi import APIRouter

from db.database import check_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness probe — reports API version and database connectivity."""
    db_status = "connected"
    try:
        await check_connection()
    except Exception as exc:  # noqa: BLE001 — report status, never crash the probe
        logger.warning("Health check DB probe failed: %s", exc)
        db_status = "disconnected"
    return {"status": "ok", "version": "0.1.0", "db": db_status}
