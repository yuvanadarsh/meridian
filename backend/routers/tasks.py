"""Scheduled-task routes: list, configure, and manage background tasks.

The generic scheduler in ``main.py`` reads the ``scheduled_tasks`` table; these
endpoints let the Settings UI add, reschedule, enable/disable, and remove tasks
without touching code. Available task *types* come from the registry.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services.tasks import TASK_REGISTRY, list_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

VALID_DAYS = {"daily", "weekdays", "weekends"}


class TaskCreate(BaseModel):
    """Create a scheduled task from a registered task type."""

    task_key: str
    display_name: str | None = None
    schedule_time: str = "08:00"
    schedule_days: str = "daily"


class TaskPatch(BaseModel):
    """Partial update — only set fields are applied."""

    display_name: str | None = None
    schedule_time: str | None = None
    schedule_days: str | None = None
    enabled: bool | None = None


def _serialize(row) -> dict:
    return {
        "id": row.id,
        "task_key": row.task_key,
        "display_name": row.display_name,
        "schedule_time": row.schedule_time,
        "schedule_days": row.schedule_days,
        "enabled": row.enabled,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "last_run_status": row.last_run_status,
        "last_run_summary": row.last_run_summary,
    }


@router.get("")
async def get_tasks(db: AsyncSession = Depends(get_db)):
    """List all scheduled tasks with their last-run info."""
    result = await db.execute(
        text(
            """
            SELECT id, task_key, display_name, schedule_time, schedule_days,
                   enabled, last_run_at, last_run_status, last_run_summary
            FROM scheduled_tasks
            ORDER BY id
            """
        )
    )
    return {"tasks": [_serialize(row) for row in result.fetchall()]}


@router.get("/available")
async def get_available_tasks():
    """List every task type from the registry — for the add-task form."""
    return {"tasks": list_tasks()}


@router.post("")
async def create_task(payload: TaskCreate, db: AsyncSession = Depends(get_db)):
    """Add a scheduled task for a known task type."""
    if payload.task_key not in TASK_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown task: {payload.task_key}")
    if payload.schedule_days not in VALID_DAYS:
        raise HTTPException(status_code=400, detail=f"Invalid days: {payload.schedule_days}")

    result = await db.execute(
        text(
            """
            INSERT INTO scheduled_tasks (task_key, display_name, schedule_time, schedule_days)
            VALUES (:task_key, :display_name, :schedule_time, :schedule_days)
            RETURNING id, task_key, display_name, schedule_time, schedule_days,
                      enabled, last_run_at, last_run_status, last_run_summary
            """
        ),
        {
            "task_key": payload.task_key,
            "display_name": payload.display_name or TASK_REGISTRY[payload.task_key].name,
            "schedule_time": payload.schedule_time,
            "schedule_days": payload.schedule_days,
        },
    )
    row = result.fetchone()
    await db.commit()
    return _serialize(row)


@router.patch("/{task_id}")
async def update_task(task_id: int, payload: TaskPatch, db: AsyncSession = Depends(get_db)):
    """Update a scheduled task (enable/disable, reschedule, rename)."""
    if payload.schedule_days is not None and payload.schedule_days not in VALID_DAYS:
        raise HTTPException(status_code=400, detail=f"Invalid days: {payload.schedule_days}")

    sets = []
    params: dict = {"id": task_id}
    for field in ("display_name", "schedule_time", "schedule_days", "enabled"):
        value = getattr(payload, field)
        if value is not None:
            sets.append(f"{field} = :{field}")
            params[field] = value
    if not sets:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await db.execute(
        text(
            f"""
            UPDATE scheduled_tasks SET {', '.join(sets)}
            WHERE id = :id
            RETURNING id, task_key, display_name, schedule_time, schedule_days,
                      enabled, last_run_at, last_run_status, last_run_summary
            """
        ),
        params,
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    return _serialize(row)


@router.delete("/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a scheduled task."""
    result = await db.execute(
        text("DELETE FROM scheduled_tasks WHERE id = :id RETURNING id"),
        {"id": task_id},
    )
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    return {"deleted": True, "id": task_id}
