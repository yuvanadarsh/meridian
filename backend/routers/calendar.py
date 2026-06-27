"""Google Calendar routes: sync and event queries."""

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import calendar_service, gmail_service, settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["calendar"])


class EventCreate(BaseModel):
    """A new calendar event. Times are ISO 8601, local timezone, no suffix."""

    account_id: int
    title: str
    start_time: str
    end_time: str
    description: str = ""


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


@router.post("/events")
async def create_event(payload: EventCreate, db: AsyncSession = Depends(get_db)):
    """Create a calendar event on an account's primary calendar."""
    await _require_account(payload.account_id, db)
    try:
        return await calendar_service.create_event(
            account_id=payload.account_id,
            title=payload.title,
            start_time=payload.start_time,
            end_time=payload.end_time,
            db=db,
            description=payload.description,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Calendar event creation failed")
        raise HTTPException(
            status_code=502, detail=f"Could not create event: {exc}"
        ) from exc


@router.get("/today")
async def today_all(db: AsyncSession = Depends(get_db)):
    """Return today's events across all connected accounts, sorted by start time."""
    accounts = await gmail_service.list_accounts(db)
    all_events: list[dict] = []
    for account in accounts:
        try:
            events = await calendar_service.get_today(account["id"], db)
            all_events.extend(events)
        except Exception:  # noqa: BLE001 — one bad account shouldn't block the rest
            logger.warning("Could not fetch today's events for account %s", account["id"])
    all_events.sort(key=lambda e: e.get("start_time") or "")
    return {"events": all_events}


async def _user_tz(db: AsyncSession) -> ZoneInfo:
    """Resolve the user's configured timezone, falling back to the default."""
    try:
        tz_value = await settings_service.get_value(db, "timezone")
        return ZoneInfo(tz_value or calendar_service.DEFAULT_TIMEZONE)
    except Exception:  # noqa: BLE001
        return ZoneInfo(calendar_service.DEFAULT_TIMEZONE)


@router.get("/range")
async def events_in_range(
    start: str = Query(..., description="Inclusive start date, YYYY-MM-DD (user timezone)"),
    end: str = Query(..., description="Exclusive end date, YYYY-MM-DD (user timezone)"),
    db: AsyncSession = Depends(get_db),
):
    """Return events across all accounts within [start, end), in the user's timezone.

    ``start``/``end`` are user-local dates. Stored event times are UTC-naive, so
    they're converted to the user's timezone for display and tagged with a
    ``day`` key (the local YYYY-MM-DD) for easy bucketing on the client.
    """
    user_tz = await _user_tz(db)
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD") from exc

    # Convert the user-local date bounds to UTC-naive to match stored columns.
    start_utc = (
        datetime.combine(start_date, time.min, tzinfo=user_tz)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    end_utc = (
        datetime.combine(end_date, time.min, tzinfo=user_tz)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    def _localize(dt: datetime | None) -> tuple[str | None, str | None]:
        """Return (iso_with_offset, local_day) for a stored UTC-naive datetime."""
        if not isinstance(dt, datetime):
            return None, None
        local = dt.replace(tzinfo=timezone.utc).astimezone(user_tz)
        return local.isoformat(), local.date().isoformat()

    accounts = await gmail_service.list_accounts(db)
    events: list[dict] = []
    for account in accounts:
        try:
            rows = await calendar_service.get_range(account["id"], start_utc, end_utc, db)
        except Exception:  # noqa: BLE001 — one bad account shouldn't block the rest
            logger.warning("Could not fetch events for account %s", account["id"])
            continue
        for row in rows:
            start_iso, day = _localize(row.get("start_time"))
            end_iso, _ = _localize(row.get("end_time"))
            events.append(
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "meet_link": row.get("meet_link"),
                    "day": day,
                }
            )

    events.sort(key=lambda e: e.get("start_time") or "")
    return {"events": events}
