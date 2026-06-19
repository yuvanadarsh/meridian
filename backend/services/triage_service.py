"""Email triage classification via Claude.

Triage is ALWAYS presented to the user for approval before any action is taken
on Gmail. Classification only writes ``triage_status`` in the database; the
single point where Gmail is mutated is ``apply_triage`` (the approve route).
"""

import asyncio
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from services import gmail_service, provider_service, settings_service

logger = logging.getLogger(__name__)

VALID_STATUSES = {"trash", "archive", "keep"}
TRIAGE_BATCH_SIZE = 50

# Extra instruction injected into the triage prompt based on the user's chosen
# aggressiveness. 'normal' keeps the balanced default (no extra instruction).
_TRIAGE_MODE_INSTRUCTIONS = {
    "aggressive": (
        "Aggressiveness: when in doubt, classify as trash. Newsletters, "
        "notifications, and automated emails should always be trash. Only keep "
        "emails that require direct personal action."
    ),
    "safe": (
        "Aggressiveness: when in doubt, classify as keep. Only trash obvious spam, "
        "OTPs, and confirmed promotional emails. Archive everything else."
    ),
    "normal": "",
}


async def _mode_instruction(db: AsyncSession) -> str:
    """Return the triage-mode instruction line to inject, or '' for normal."""
    mode = await settings_service.get_value(db, "triage_mode")
    instruction = _TRIAGE_MODE_INSTRUCTIONS.get(mode, "")
    return f"\n{instruction}\n" if instruction else ""
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


async def classify_email(email: dict, db: AsyncSession) -> str:
    """Classify a single email. Defaults to 'keep' on any ambiguity (never auto-trash)."""
    prompt = PROMPT_TEMPLATE.format(
        from_address=email.get("from_address") or "",
        subject=email.get("subject") or "",
        snippet=email.get("snippet") or "",
        labels=", ".join(email.get("labels") or []),
    )
    prompt += await _mode_instruction(db)

    raw = (await provider_service.call_classify(db, prompt, max_tokens=10)).lower()
    for status in ("trash", "archive", "keep"):
        if status in raw:
            return status
    return "keep"  # safe default — never destructive on ambiguity


def _extract_json_array(raw: str) -> str:
    """Slice out the first JSON array from a model reply (tolerates fences/prose)."""
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return "[]"
    return raw[start : end + 1]


async def classify_and_summarize_batch(emails: list[dict], db: AsyncSession) -> list[dict]:
    """Classify AND summarize a batch of emails in a single provider call.

    One call per batch (rather than per email) keeps the sweep fast. Returns a
    list aligned with ``emails``, each ``{"status", "summary"}``. Any failure or
    malformed reply degrades to ``keep`` with an empty summary — triage is never
    destructive on ambiguity, and the user approves everything before it applies.
    """
    if not emails:
        return []

    lines = []
    for index, email in enumerate(emails, 1):
        sender = (email.get("from_address") or "")[:120]
        subject = (email.get("subject") or "").replace("\n", " ")[:200]
        snippet = (email.get("snippet") or "").replace("\n", " ")[:200]
        lines.append(f"{index}. From: {sender} | Subject: {subject} | Snippet: {snippet}")

    prompt = (
        "Classify each email and write a one-sentence summary of it.\n"
        f"Return ONLY a JSON array of exactly {len(emails)} objects, in the same "
        "order as the emails, with no other text:\n"
        '[{"status": "trash|archive|keep", "summary": "one sentence"}, ...]\n\n'
        "Categories:\n"
        "- trash: OTPs, promotional/marketing (List-Unsubscribe header or "
        "CATEGORY_PROMOTIONS label), automated notifications with no action needed, "
        "bounce messages, unsubscribe confirmations\n"
        "- archive: past human-to-human conversations, receipts, shipping notices, "
        "GitHub/GitLab notifications, newsletters, threads already replied to\n"
        "- keep: needs a response or action, contracts/agreements/legal documents, "
        "calendar invitations, direct personal correspondence\n"
        + await _mode_instruction(db)
        + "\nEmails:\n"
        + "\n".join(lines)
    )

    fallback = [{"status": "keep", "summary": ""} for _ in emails]
    try:
        reply = await provider_service.call_classify(db, prompt, max_tokens=3000)
        data = json.loads(_extract_json_array(reply))
    except Exception as exc:  # noqa: BLE001 — keep the sweep going past a bad batch
        logger.error("Batch triage failed for %s emails: %s", len(emails), exc)
        return fallback

    if not isinstance(data, list) or len(data) != len(emails):
        logger.warning(
            "Batch triage returned %s items, expected %s — defaulting to keep",
            len(data) if isinstance(data, list) else "non-list",
            len(emails),
        )
        return fallback

    results = []
    for item in data:
        if not isinstance(item, dict):
            results.append({"status": "keep", "summary": ""})
            continue
        status = str(item.get("status", "keep")).lower().strip()
        if status not in VALID_STATUSES:
            status = "keep"
        results.append({"status": status, "summary": str(item.get("summary") or "").strip()})
    return results


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
                status = await classify_email(email, db)
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


async def get_triage_emails(
    account_id: int,
    db: AsyncSession,
    status: str,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return one page of emails in a triage category, newest first, with summaries."""
    result = await db.execute(
        text(
            """
            SELECT id, from_address, subject, summary, received_at
            FROM emails
            WHERE account_id = :account_id AND triage_status = :status
            ORDER BY received_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
            """
        ),
        {"account_id": account_id, "status": status, "limit": limit, "offset": offset},
    )
    return {"emails": [dict(row) for row in result.mappings().all()]}


async def build_triage_report(account_id: int, db: AsyncSession) -> str:
    """Build a plain-text report of every triaged email, grouped by category."""
    result = await db.execute(
        text(
            """
            SELECT triage_status, from_address, subject, summary, received_at
            FROM emails
            WHERE account_id = :account_id
              AND triage_status IN ('trash', 'archive', 'keep')
            ORDER BY triage_status, received_at DESC NULLS LAST
            """
        ),
        {"account_id": account_id},
    )
    rows = result.mappings().all()
    lines = [f"Meridian triage report — account {account_id}", ""]
    for status in ("trash", "archive", "keep"):
        items = [row for row in rows if row["triage_status"] == status]
        lines.append(f"## {status.upper()} ({len(items)})")
        for row in items:
            when = row["received_at"].date().isoformat() if row["received_at"] else "????-??-??"
            sender = row["from_address"] or "(unknown sender)"
            subject = row["subject"] or "(no subject)"
            lines.append(f"- [{when}] {sender} — {subject}")
            if row["summary"]:
                lines.append(f"    {row['summary']}")
        lines.append("")
    return "\n".join(lines)


async def discard_sweep(account_id: int, db: AsyncSession) -> dict:
    """Throw away an account's swept emails locally and reset its progress.

    Local only — Gmail is never touched. Used by the "Discard Sweep" action.
    """
    await db.execute(
        text(
            """
            UPDATE calendar_events SET source_email_id = NULL
            WHERE source_email_id IN (SELECT id FROM emails WHERE account_id = :account_id)
            """
        ),
        {"account_id": account_id},
    )
    result = await db.execute(
        text("DELETE FROM emails WHERE account_id = :account_id"),
        {"account_id": account_id},
    )
    await db.execute(
        text(
            """
            UPDATE sweep_progress
            SET status = 'idle', total_estimated = 0, fetched = 0, stored = 0,
                skipped = 0, error = NULL, sweep_completed_at = NULL, updated_at = NOW()
            WHERE account_id = :account_id
            """
        ),
        {"account_id": account_id},
    )
    await db.commit()
    return {"discarded": result.rowcount or 0}


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def apply_triage(
    account_id: int, db: AsyncSession, overrides: list[dict] | None = None
) -> dict:
    """Apply approved triage to Gmail. THE ONLY PLACE GMAIL IS MUTATED.

    ``overrides`` carries the emails the user re-categorized during review
    (``[{"id", "status"}]``); they are persisted first, then the stored
    categories are applied:

    - trash:   moved to Gmail trash, then deleted from the database
    - archive: removed from the Gmail inbox, kept in the database
    - keep:    untouched
    """
    # Persist the user's review overrides before reading stored statuses.
    for override in overrides or []:
        if override.get("status") in VALID_STATUSES:
            await db.execute(
                text(
                    "UPDATE emails SET triage_status = :status "
                    "WHERE id = :id AND account_id = :account_id"
                ),
                {"status": override["status"], "id": override["id"], "account_id": account_id},
            )
    if overrides:
        await db.commit()

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
    # Mark the sweep as fully applied so the "Review triage" button is removed.
    await db.execute(
        text(
            "UPDATE sweep_progress SET status = 'completed', sweep_completed_at = NULL, "
            "updated_at = NOW() WHERE account_id = :account_id"
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


async def bulk_update_triage_status(
    db: AsyncSession,
    changes: list[tuple[int, str]],
) -> int:
    """Update triage_status for multiple emails in one transaction.

    Args:
        changes: List of (email_id, new_triage_status) pairs.

    Returns:
        Number of rows updated.
    """
    if not changes:
        return 0
    updated = 0
    for email_id, status in changes:
        result = await db.execute(
            text("UPDATE emails SET triage_status = :status WHERE id = :id"),
            {"status": status, "id": email_id},
        )
        updated += result.rowcount  # type: ignore[attr-defined]
    await db.commit()
    return updated
