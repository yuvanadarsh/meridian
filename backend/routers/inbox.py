"""Inbox routes: the continuous email queue shown on the Inbox page.

The email poll classifies new mail on arrival into ``email_queue``. These routes
expose that queue, let the user generate a draft for reply-worthy mail, and —
the ONLY point where Gmail is mutated — apply approved trash/archive actions.
Nothing here touches Gmail without the user explicitly approving it.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import draft_service, gmail_service
from services.tasks import get_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["inbox"])

# Classifications that result in a Gmail mutation on approval.
_GMAIL_ACTIONS = {"trash", "archive"}


class ApprovePayload(BaseModel):
    """Queue item ids to approve, with optional per-item classification overrides.

    ``overrides`` maps a queue item id (string, since JSON keys are strings) to
    the final classification the user picked in the Inbox before approving.
    """

    ids: list[int] = []
    overrides: dict[str, str] = {}


@router.get("/queue")
async def get_queue(db: AsyncSession = Depends(get_db)):
    """Return all unapproved queue items, newest first, joined with email detail."""
    result = await db.execute(
        text(
            """
            SELECT
                eq.id, eq.email_id, eq.classification, eq.ai_summary,
                eq.needs_draft, eq.draft_id, eq.draft_status, eq.created_at,
                e.subject, e.from_address, e.received_at, e.snippet
            FROM email_queue eq
            JOIN emails e ON eq.email_id = e.id
            WHERE eq.approved_at IS NULL
            ORDER BY eq.created_at DESC
            """
        )
    )
    return [dict(row._mapping) for row in result.fetchall()]


@router.get("/queue/summary")
async def get_queue_summary(db: AsyncSession = Depends(get_db)):
    """Return per-classification counts of the unapproved queue (for chat + header)."""
    result = await db.execute(
        text(
            """
            SELECT classification, COUNT(*) AS count
            FROM email_queue
            WHERE approved_at IS NULL
            GROUP BY classification
            """
        )
    )
    summary = {row.classification: row.count for row in result.fetchall()}
    return {
        "trash": summary.get("trash", 0),
        "archive": summary.get("archive", 0),
        "keep": summary.get("keep", 0),
        "draft": summary.get("draft", 0),
        "total": sum(summary.values()),
    }


@router.get("/trigger")
async def trigger_poll(db: AsyncSession = Depends(get_db)):
    """Manually run the email poll now (fetch + triage) and return the fresh queue."""
    task = get_task("email_poll")
    if not task:
        raise HTTPException(status_code=500, detail="Email poll task not registered")
    result = await task.safe_run(db)
    return {"result": result, "queue": await get_queue(db)}


@router.post("/approve")
async def approve_items(
    payload: ApprovePayload = ApprovePayload(),
    db: AsyncSession = Depends(get_db),
):
    """Approve selected queue items, applying trash/archive to Gmail per item.

    Per classification (after applying any override):
    - trash:   moved to Gmail trash, then the email row is deleted locally
    - archive: removed from the Gmail inbox, kept locally
    - keep / draft: no Gmail mutation; the queue entry is just marked approved

    This is the single point where the Inbox mutates Gmail. Trashing/archiving
    is batched per account to stay within Gmail's batchModify limits.
    """
    if not payload.ids:
        return {"approved": 0, "trashed": 0, "archived": 0}

    result = await db.execute(
        text(
            """
            SELECT eq.id, eq.email_id, eq.classification, e.gmail_id, e.account_id
            FROM email_queue eq
            JOIN emails e ON eq.email_id = e.id
            WHERE eq.id = ANY(:ids) AND eq.approved_at IS NULL
            """
        ),
        {"ids": payload.ids},
    )
    items = [dict(row._mapping) for row in result.fetchall()]

    # Resolve the final classification per item (override wins), then group the
    # Gmail ids that need a mutation by (account_id, action).
    trash_ids: list[int] = []          # email_queue ids to trash
    by_account: dict[int, dict[str, list[str]]] = {}
    for item in items:
        classification = payload.overrides.get(str(item["id"]), item["classification"])
        if classification in _GMAIL_ACTIONS and item["gmail_id"]:
            account = by_account.setdefault(item["account_id"], {"trash": [], "archive": []})
            account[classification].append(item["gmail_id"])
        if classification == "trash":
            trash_ids.append(item["email_id"])

    trashed = 0
    archived = 0
    for account_id, actions in by_account.items():
        try:
            creds = await gmail_service.load_credentials(db, account_id)
            service = await asyncio.to_thread(
                lambda: gmail_service.build(
                    "gmail", "v1", credentials=creds, cache_discovery=False
                )
            )
            for chunk in _chunked(actions["archive"], 500):
                await asyncio.to_thread(
                    lambda body=chunk: service.users()
                    .messages()
                    .batchModify(userId="me", body={"ids": body, "removeLabelIds": ["INBOX"]})
                    .execute()
                )
                archived += len(chunk)
            for chunk in _chunked(actions["trash"], 500):
                await asyncio.to_thread(
                    lambda body=chunk: service.users()
                    .messages()
                    .batchModify(
                        userId="me",
                        body={"ids": body, "addLabelIds": ["TRASH"], "removeLabelIds": ["INBOX"]},
                    )
                    .execute()
                )
                trashed += len(chunk)
        except Exception:  # noqa: BLE001 — one account failing shouldn't abort the rest
            logger.exception("Failed to apply Gmail actions for account %s", account_id)

    # Mark every selected item approved before any local deletes.
    await db.execute(
        text(
            "UPDATE email_queue SET approved_at = NOW() "
            "WHERE id = ANY(:ids) AND approved_at IS NULL"
        ),
        {"ids": payload.ids},
    )
    # Trashed emails are deleted locally after being trashed in Gmail. The queue
    # row is removed via ON DELETE CASCADE.
    if trash_ids:
        await db.execute(
            text("DELETE FROM emails WHERE id = ANY(:ids)"),
            {"ids": trash_ids},
        )
    await db.commit()

    logger.info(
        "Inbox approve: %s items, trashed=%s archived=%s", len(items), trashed, archived
    )
    return {"approved": len(items), "trashed": trashed, "archived": archived}


@router.post("/queue/{item_id}/generate-draft")
async def generate_draft_for_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Generate a reply draft for one queue item and link it back to the queue."""
    result = await db.execute(
        text(
            """
            SELECT eq.id, eq.email_id, e.account_id, e.from_address, e.subject, e.body_text
            FROM email_queue eq
            JOIN emails e ON eq.email_id = e.id
            WHERE eq.id = :id
            """
        ),
        {"id": item_id},
    )
    item = result.mappings().first()
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")

    await db.execute(
        text("UPDATE email_queue SET draft_status = 'generating' WHERE id = :id"),
        {"id": item_id},
    )
    await db.commit()

    try:
        draft = await draft_service.generate_draft(
            account_id=item["account_id"],
            to_email=item["from_address"],
            subject=f"Re: {item['subject']}" if item["subject"] else "Re:",
            context=f"Reply to this email: {(item['body_text'] or '')[:1000]}",
            db=db,
            thread_email_id=item["email_id"],
        )
    except Exception as exc:  # noqa: BLE001
        await db.execute(
            text("UPDATE email_queue SET draft_status = NULL WHERE id = :id"),
            {"id": item_id},
        )
        await db.commit()
        logger.exception("Draft generation failed for queue item %s", item_id)
        raise HTTPException(status_code=502, detail=f"Draft generation failed: {exc}") from exc

    draft_id = draft.get("id")
    await db.execute(
        text(
            "UPDATE email_queue SET draft_id = :draft_id, draft_status = 'ready' "
            "WHERE id = :id"
        ),
        {"draft_id": draft_id, "id": item_id},
    )
    await db.commit()
    return {"draft_id": draft_id, "status": "ready"}


@router.delete("/queue/{item_id}")
async def dismiss_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Dismiss one queue item without taking any action (Gmail untouched)."""
    result = await db.execute(
        text("DELETE FROM email_queue WHERE id = :id RETURNING id"),
        {"id": item_id},
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    await db.commit()
    return {"dismissed": True, "id": item_id}


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]
