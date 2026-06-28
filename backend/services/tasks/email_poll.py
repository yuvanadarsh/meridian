"""Email poll task — fetch new mail from all accounts and triage it on arrival.

Runs every 15 minutes. For each account it pulls new messages into the
``emails`` table, classifies them immediately into one of trash/archive/keep/
draft, and inserts a row into ``email_queue`` for the Inbox page. Nothing is
applied to Gmail here — the queue accumulates until the user approves it.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from .base import BaseTask

logger = logging.getLogger(__name__)

# Classify new mail in chunks to keep each Claude call bounded.
TRIAGE_CHUNK_SIZE = 25


async def triage_new_emails(account_id: int, email_ids: list[int], db) -> list[dict]:
    """Classify freshly-polled emails and persist their triage status.

    Fetches the given email rows, classifies them in batches of
    ``TRIAGE_CHUNK_SIZE`` via the 4-category continuous classifier, writes each
    result back to ``emails.triage_status`` and ``emails.summary``, and returns
    a list of ``{email_id, classification, summary}`` for the caller to queue.
    """
    from services import triage_service

    if not email_ids:
        return []

    result = await db.execute(
        text(
            """
            SELECT id, from_address, subject, snippet
            FROM emails
            WHERE id = ANY(:ids)
            ORDER BY id
            """
        ),
        {"ids": email_ids},
    )
    rows = [dict(row) for row in result.mappings().all()]

    triaged: list[dict] = []
    for start in range(0, len(rows), TRIAGE_CHUNK_SIZE):
        batch = rows[start : start + TRIAGE_CHUNK_SIZE]
        classifications = await triage_service.classify_emails(batch, db)
        for email, outcome in zip(batch, classifications):
            classification = outcome["classification"]
            summary = outcome["summary"]
            await db.execute(
                text(
                    "UPDATE emails SET triage_status = :status, summary = :summary "
                    "WHERE id = :id"
                ),
                {"status": classification, "summary": summary, "id": email["id"]},
            )
            triaged.append(
                {
                    "email_id": email["id"],
                    "classification": classification,
                    "summary": summary,
                }
            )
        await db.commit()

    return triaged


class EmailPollTask(BaseTask):
    """Fetch new emails from every connected Gmail account and triage on arrival."""

    name = "Email Sync"
    description = "Fetches and triages new emails from all connected Gmail accounts every 15 minutes"
    default_schedule = "*/15"
    default_days = "daily"

    async def run(self, db) -> dict:
        from services import gmail_service

        accounts = await gmail_service.list_accounts(db)
        total_new = 0
        total_triaged = 0

        for account in accounts:
            # Look back from the account's last sync; fall back to 24h on first run.
            last_sync = account.get("last_synced_at") or (
                datetime.utcnow() - timedelta(hours=24)
            )
            new_ids = await gmail_service.fetch_new_emails_since(
                account_id=account["id"], since=last_sync, db=db
            )
            total_new += len(new_ids)

            if new_ids:
                # Classify the new mail immediately and add it to the inbox queue.
                triaged = await triage_new_emails(account["id"], new_ids, db)
                total_triaged += len(triaged)

                for item in triaged:
                    await db.execute(
                        text(
                            """
                            INSERT INTO email_queue
                                (email_id, account_id, classification, ai_summary, needs_draft)
                            VALUES
                                (:email_id, :account_id, :classification, :summary, :needs_draft)
                            ON CONFLICT (email_id) DO NOTHING
                            """
                        ),
                        {
                            "email_id": item["email_id"],
                            "account_id": account["id"],
                            "classification": item["classification"],
                            "summary": item["summary"],
                            "needs_draft": item["classification"] == "draft",
                        },
                    )
                await db.commit()

            await db.execute(
                text("UPDATE gmail_accounts SET last_synced_at = NOW() WHERE id = :id"),
                {"id": account["id"]},
            )
            await db.commit()

        return {
            "status": "success",
            "summary": (
                f"Fetched {total_new} new emails across {len(accounts)} accounts, "
                f"triaged {total_triaged}"
            ),
            "data": {"new_email_count": total_new, "triaged": total_triaged},
        }
