"""Email triage classification via Claude.

Triage is ALWAYS presented to the user for approval before any action is taken
on Gmail. Classification only writes ``triage_status`` in the database; the
single point where Gmail is mutated is ``apply_triage`` (the approve route).
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from services import claude_service, gmail_service

logger = logging.getLogger(__name__)

VALID_STATUSES = {"trash", "archive", "keep"}
TRIAGE_BATCH_SIZE = 50
# Cap concurrent Claude calls so a large mailbox doesn't trip rate limits.
MAX_CONCURRENCY = 5

PROMPT_TEMPLATE = """Classify this email as exactly one of: trash, archive, keep.

trash: OTPs, promotional/marketing, automated system notifications with no action needed,
       bounce messages, unsubscribe confirmations, emails with List-Unsubscribe headers,
       Gmail CATEGORY_PROMOTIONS label
archive: Past human-to-human conversations, receipts, shipping notifications, GitHub/GitLab
         notifications, newsletters, emails already replied to
keep: Emails requiring response or action, contracts/agreements/legal documents,
      calendar invitations, direct personal correspondence, anything addressed personally

Email:
From: {from_address}
Subject: {subject}
Snippet: {snippet}
Labels: {labels}

Reply with only the single word: trash, archive, or keep"""


async def classify_email(email: dict) -> str:
    """Classify a single email. Defaults to 'keep' on any ambiguity (never auto-trash)."""
    client = claude_service.get_client()
    prompt = PROMPT_TEMPLATE.format(
        from_address=email.get("from_address") or "",
        subject=email.get("subject") or "",
        snippet=email.get("snippet") or "",
        labels=", ".join(email.get("labels") or []),
    )

    message = await client.messages.create(
        model=claude_service.MODEL,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = claude_service.extract_text(message).lower()
    for status in ("trash", "archive", "keep"):
        if status in raw:
            return status
    return "keep"  # safe default — never destructive on ambiguity


async def triage_account(account_id: int, db: AsyncSession) -> dict:
    """Classify every pending email for an account, writing results to the DB.

    Processes in batches; results are stored as triage_status but NOT applied to
    Gmail. The user reviews and approves before anything is mutated.
    """
    result = await db.execute(
        text(
            """
            SELECT id, from_address, subject, snippet
            FROM emails
            WHERE account_id = :account_id AND triage_status = 'pending'
            ORDER BY id
            """
        ),
        {"account_id": account_id},
    )
    pending = [dict(row) for row in result.mappings().all()]
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def classify_one(email: dict) -> tuple[int, str]:
        async with semaphore:
            try:
                status = await classify_email(email)
            except Exception as exc:  # noqa: BLE001 — keep going past one failure
                logger.error("Failed to classify email %s: %s", email["id"], exc)
                status = "keep"
            return email["id"], status

    classified = 0
    for start in range(0, len(pending), TRIAGE_BATCH_SIZE):
        batch = pending[start : start + TRIAGE_BATCH_SIZE]
        results = await asyncio.gather(*(classify_one(email) for email in batch))
        for email_id, status in results:
            await db.execute(
                text("UPDATE emails SET triage_status = :status WHERE id = :id"),
                {"status": status, "id": email_id},
            )
        await db.commit()
        classified += len(results)
        logger.info(
            "Triaged %s/%s emails for account %s", classified, len(pending), account_id
        )

    return {"classified": classified}


async def run_triage_background(account_id: int) -> None:
    """Entry point for FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await triage_account(account_id, db)
        except Exception:  # noqa: BLE001
            logger.exception("Background triage failed for account %s", account_id)


async def get_triage_results(account_id: int, db: AsyncSession) -> dict:
    """Return per-category counts and a sample of emails for user review."""
    counts_result = await db.execute(
        text(
            """
            SELECT triage_status, COUNT(*) AS count
            FROM emails WHERE account_id = :account_id
            GROUP BY triage_status
            """
        ),
        {"account_id": account_id},
    )
    counts = {"trash": 0, "archive": 0, "keep": 0, "pending": 0}
    for row in counts_result.mappings().all():
        counts[row["triage_status"]] = row["count"]

    samples: dict[str, list[dict]] = {}
    for status in ("trash", "archive", "keep"):
        sample_result = await db.execute(
            text(
                """
                SELECT id, from_address, subject, snippet, received_at
                FROM emails
                WHERE account_id = :account_id AND triage_status = :status
                ORDER BY received_at DESC NULLS LAST
                LIMIT 10
                """
            ),
            {"account_id": account_id, "status": status},
        )
        samples[status] = [dict(row) for row in sample_result.mappings().all()]

    return {"counts": counts, "samples": samples}


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def apply_triage(account_id: int, db: AsyncSession) -> dict:
    """Apply approved triage to Gmail. THE ONLY PLACE GMAIL IS MUTATED.

    - trash:   moved to Gmail trash, then deleted from the database
    - archive: removed from the Gmail inbox, kept in the database
    - keep:    untouched
    """
    creds = await gmail_service.load_credentials(db, account_id)
    service = await asyncio.to_thread(
        lambda: gmail_service.build("gmail", "v1", credentials=creds, cache_discovery=False)
    )

    async def gmail_ids_for(status: str) -> list[str]:
        rows = await db.execute(
            text(
                "SELECT gmail_id FROM emails "
                "WHERE account_id = :account_id AND triage_status = :status"
            ),
            {"account_id": account_id, "status": status},
        )
        return [row[0] for row in rows.all()]

    trash_ids = await gmail_ids_for("trash")
    archive_ids = await gmail_ids_for("archive")

    # Gmail's batchModify accepts up to 1000 ids; chunk to stay well under.
    for chunk in _chunked(archive_ids, 500):
        await asyncio.to_thread(
            lambda body=chunk: service.users()
            .messages()
            .batchModify(userId="me", body={"ids": body, "removeLabelIds": ["INBOX"]})
            .execute()
        )

    for chunk in _chunked(trash_ids, 500):
        await asyncio.to_thread(
            lambda body=chunk: service.users()
            .messages()
            .batchModify(
                userId="me",
                body={"ids": body, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
            )
            .execute()
        )

    # Trash is deleted from the local DB after being trashed in Gmail.
    await db.execute(
        text(
            "DELETE FROM emails WHERE account_id = :account_id AND triage_status = 'trash'"
        ),
        {"account_id": account_id},
    )
    await db.commit()

    logger.info(
        "Applied triage for account %s: trashed=%s archived=%s",
        account_id,
        len(trash_ids),
        len(archive_ids),
    )
    return {"trashed": len(trash_ids), "archived": len(archive_ids)}
