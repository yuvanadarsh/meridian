"""Calendar sync task — refresh calendar events for every connected account."""

import logging

from .base import BaseTask

logger = logging.getLogger(__name__)


class CalendarSyncTask(BaseTask):
    """Pull recent and upcoming events from Google Calendar into the local DB."""

    name = "Calendar Sync"
    description = "Refreshes calendar events from now-7d to now+30d for every account"
    default_schedule = "07:00"
    default_days = "daily"

    async def run(self, db) -> dict:
        from services import calendar_service, gmail_service

        accounts = await gmail_service.list_accounts(db)
        total_synced = 0
        for account in accounts:
            result = await calendar_service.sync_calendar(account["id"], db)
            total_synced += int(result.get("synced", 0))

        return {
            "status": "success",
            "summary": f"Synced {total_synced} events across {len(accounts)} accounts",
            "data": {"synced": total_synced, "accounts": len(accounts)},
        }
