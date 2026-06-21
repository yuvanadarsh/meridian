"""Email poll task — fetch new mail from all accounts every 15 minutes.

Makes no Claude calls: it only pulls new messages into the ``emails`` table as
``pending`` so they're ready for the afternoon review. The scheduler runs this on
its own interval rather than at a fixed clock time.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from .base import BaseTask

logger = logging.getLogger(__name__)


class EmailPollTask(BaseTask):
    """Fetch new emails from every connected Gmail account."""

    name = "Email Sync"
    description = "Fetches new emails from all connected Gmail accounts every 15 minutes"
    default_schedule = "*/15"
    default_days = "daily"

    async def run(self, db) -> dict:
        from services import gmail_service

        accounts = await gmail_service.list_accounts(db)
        total_new = 0

        for account in accounts:
            # Look back from the account's last sync; fall back to 24h on first run.
            last_sync = account.get("last_synced_at") or (
                datetime.utcnow() - timedelta(hours=24)
            )
            new_ids = await gmail_service.fetch_new_emails_since(
                account_id=account["id"], since=last_sync, db=db
            )
            total_new += len(new_ids)

            await db.execute(
                text("UPDATE gmail_accounts SET last_synced_at = NOW() WHERE id = :id"),
                {"id": account["id"]},
            )

        await db.commit()
        return {
            "status": "success",
            "summary": f"Fetched {total_new} new emails across {len(accounts)} accounts",
            "data": {"new_email_count": total_new},
        }
