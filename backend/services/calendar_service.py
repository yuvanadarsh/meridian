"""Google Calendar sync.

Reuses the OAuth credentials stored per account (the same grant covers Gmail
and Calendar). Syncs the recent past and near future into calendar_events.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services import gmail_service

logger = logging.getLogger(__name__)

PAST_WINDOW_DAYS = 7
FUTURE_WINDOW_DAYS = 30


def _utc_naive(dt: datetime) -> datetime:
    """Normalize an aware datetime to naive UTC (matches the TIMESTAMP columns)."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_event_time(time_obj: dict | None) -> datetime | None:
    """Parse a Google event start/end, handling timed and all-day events."""
    if not time_obj:
        return None
    if time_obj.get("dateTime"):
        parsed = datetime.fromisoformat(time_obj["dateTime"])
        return _utc_naive(parsed) if parsed.tzinfo else parsed
    if time_obj.get("date"):  # all-day event
        return datetime.fromisoformat(time_obj["date"])
    return None


def _extract_meet_link(event: dict) -> str | None:
    """Prefer the Hangout link, fall back to a video conference entry point."""
    if event.get("hangoutLink"):
        return event["hangoutLink"]
    for entry in event.get("conferenceData", {}).get("entryPoints", []):
        if entry.get("entryPointType") == "video" and entry.get("uri"):
            return entry["uri"]
    return None


def _attendee_emails(event: dict) -> list[str]:
    return [a["email"] for a in event.get("attendees", []) if a.get("email")]


async def sync_calendar(account_id: int, db: AsyncSession) -> dict:
    """Fetch events from now-7d to now+30d and upsert them."""
    creds = await gmail_service.load_credentials(db, account_id)
    service = await asyncio.to_thread(
        lambda: gmail_service.build(
            "calendar", "v3", credentials=creds, cache_discovery=False
        )
    )

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=PAST_WINDOW_DAYS)).isoformat().replace("+00:00", "Z")
    time_max = (now + timedelta(days=FUTURE_WINDOW_DAYS)).isoformat().replace("+00:00", "Z")

    events: list[dict] = []
    page_token: str | None = None
    while True:
        response = await asyncio.to_thread(
            lambda: service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,  # expand recurring events into instances
                orderBy="startTime",
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    synced = 0
    for event in events:
        if event.get("status") == "cancelled":
            continue
        await db.execute(
            text(
                """
                INSERT INTO calendar_events (
                    account_id, google_event_id, title, description,
                    start_time, end_time, attendees, meet_link
                )
                VALUES (
                    :account_id, :google_event_id, :title, :description,
                    :start_time, :end_time, :attendees, :meet_link
                )
                ON CONFLICT (google_event_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    attendees = EXCLUDED.attendees,
                    meet_link = EXCLUDED.meet_link
                """
            ),
            {
                "account_id": account_id,
                "google_event_id": event["id"],
                "title": event.get("summary"),
                "description": event.get("description"),
                "start_time": _parse_event_time(event.get("start")),
                "end_time": _parse_event_time(event.get("end")),
                "attendees": _attendee_emails(event),
                "meet_link": _extract_meet_link(event),
            },
        )
        synced += 1

    await db.execute(
        text("UPDATE gmail_accounts SET last_synced_at = NOW() WHERE id = :id"),
        {"id": account_id},
    )
    await db.commit()
    logger.info("Calendar sync for account %s: %s events", account_id, synced)
    return {"synced": synced}


# Meridian assumes the user's local timezone for events created from chat.
DEFAULT_TIMEZONE = "America/New_York"


async def create_event(
    account_id: int,
    title: str,
    start_time: str,
    end_time: str,
    db: AsyncSession,
    description: str = "",
) -> dict:
    """Create a Google Calendar event and mirror it into ``calendar_events``.

    ``start_time`` / ``end_time`` are ISO 8601 strings without a timezone
    suffix; they're interpreted in ``DEFAULT_TIMEZONE``. Returns the Google API
    insert result.
    """
    creds = await gmail_service.load_credentials(db, account_id)
    service = await asyncio.to_thread(
        lambda: gmail_service.build(
            "calendar", "v3", credentials=creds, cache_discovery=False
        )
    )

    event_body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_time, "timeZone": DEFAULT_TIMEZONE},
        "end": {"dateTime": end_time, "timeZone": DEFAULT_TIMEZONE},
    }
    result = await asyncio.to_thread(
        lambda: service.events()
        .insert(calendarId="primary", body=event_body)
        .execute()
    )

    # Mirror into our local table so it shows up in digests/context immediately.
    await db.execute(
        text(
            """
            INSERT INTO calendar_events (
                account_id, google_event_id, title, description,
                start_time, end_time, attendees, meet_link
            )
            VALUES (
                :account_id, :google_event_id, :title, :description,
                :start_time, :end_time, :attendees, :meet_link
            )
            ON CONFLICT (google_event_id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time
            """
        ),
        {
            "account_id": account_id,
            "google_event_id": result["id"],
            "title": result.get("summary", title),
            "description": result.get("description", description),
            "start_time": _parse_event_time(result.get("start")),
            "end_time": _parse_event_time(result.get("end")),
            "attendees": _attendee_emails(result),
            "meet_link": _extract_meet_link(result),
        },
    )
    await db.commit()
    logger.info("Created calendar event %s for account %s", result["id"], account_id)
    return result


_EVENT_COLUMNS = (
    "id, google_event_id, title, description, start_time, end_time, attendees, meet_link"
)


async def get_today(account_id: int, db: AsyncSession) -> list[dict]:
    """Return today's events (UTC day) sorted by start time."""
    start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    end = start + timedelta(days=1)
    result = await db.execute(
        text(
            f"""
            SELECT {_EVENT_COLUMNS}
            FROM calendar_events
            WHERE account_id = :account_id
              AND start_time >= :start AND start_time < :end
            ORDER BY start_time
            """
        ),
        {"account_id": account_id, "start": start, "end": end},
    )
    return [dict(row) for row in result.mappings().all()]


async def get_upcoming(account_id: int, db: AsyncSession, days: int = 7) -> list[dict]:
    """Return events from now through the next ``days`` days, sorted by start time."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    end = now + timedelta(days=days)
    result = await db.execute(
        text(
            f"""
            SELECT {_EVENT_COLUMNS}
            FROM calendar_events
            WHERE account_id = :account_id
              AND start_time >= :now AND start_time < :end
            ORDER BY start_time
            """
        ),
        {"account_id": account_id, "now": now, "end": end},
    )
    return [dict(row) for row in result.mappings().all()]
