"""Drafts routes: generate, review, edit, send, and discard email drafts."""

import asyncio
import logging
import os
import re
from datetime import datetime

import aiofiles
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from models.draft import DraftEdit, DraftGenerateRequest, DraftOut
from services import draft_service, gmail_service, obsidian_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drafts", tags=["drafts"])


async def embed_sent_email(draft: dict, sent_at: datetime) -> None:
    """Write a sent email to the Obsidian vault for a permanent record.

    Best-effort and non-blocking by contract: callers must not let a failure
    here fail the send. No-op when no vault is configured.
    """
    vault = obsidian_service.vault_path()
    if vault is None:
        return

    sent_dir = vault / "Sent"
    await asyncio.to_thread(os.makedirs, sent_dir, exist_ok=True)

    subject = draft.get("subject") or "No Subject"
    to_email = draft.get("to_email") or ""
    safe_subject = re.sub(r"[^\w\s-]", "", subject)[:60].strip() or "No Subject"
    file_path = sent_dir / f"{sent_at.strftime('%Y-%m-%d')}-{safe_subject}.md"

    contact = to_email.split("@")[0] if to_email else "Unknown"
    content = (
        f"# {subject}\n\n"
        f"*Sent: {sent_at.strftime('%B %d, %Y at %I:%M %p')} · To: {to_email}*\n\n"
        f"## Content\n\n{draft.get('body') or ''}\n\n"
        f"## Related\n- [[{contact}]]\n"
    )

    async with aiofiles.open(file_path, "w", encoding="utf-8") as handle:
        await handle.write(content)
    logger.info("Sent email embedded to Obsidian: %s", file_path)

_DRAFT_COLUMNS = (
    "id, account_id, to_email, subject, body, thread_email_id, status, "
    "created_at, updated_at"
)


@router.post("/generate", response_model=DraftOut)
async def generate(payload: DraftGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate a draft email in the user's voice and store it as pending."""
    try:
        draft = await draft_service.generate_draft(
            account_id=payload.account_id,
            to_email=payload.to_email,
            subject=payload.subject,
            context=payload.context,
            db=db,
            thread_email_id=payload.thread_email_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Draft generation failed")
        raise HTTPException(status_code=502, detail=f"Draft generation failed: {exc}") from exc
    return DraftOut(**draft)


@router.get("", response_model=list[DraftOut])
async def list_drafts(db: AsyncSession = Depends(get_db)):
    """Return all pending drafts, newest first."""
    result = await db.execute(
        text(
            f"SELECT {_DRAFT_COLUMNS} FROM drafts "
            "WHERE status = 'pending' ORDER BY created_at DESC"
        )
    )
    return [DraftOut(**dict(row)) for row in result.mappings().all()]


@router.patch("/{draft_id}", response_model=DraftOut)
async def edit_draft(
    draft_id: int, payload: DraftEdit, db: AsyncSession = Depends(get_db)
):
    """Update a draft's body."""
    result = await db.execute(
        text(
            f"UPDATE drafts SET body = :body, updated_at = NOW() "
            f"WHERE id = :id RETURNING {_DRAFT_COLUMNS}"
        ),
        {"body": payload.body, "id": draft_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    await db.commit()
    return DraftOut(**dict(row))


@router.post("/{draft_id}/send", response_model=DraftOut)
async def send_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    """Send a pending draft via the Gmail API and mark it sent."""
    result = await db.execute(
        text(f"SELECT {_DRAFT_COLUMNS} FROM drafts WHERE id = :id"),
        {"id": draft_id},
    )
    draft = result.mappings().first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft["account_id"] is None:
        raise HTTPException(status_code=400, detail="Draft has no sending account")

    # If this draft replies to a known email, keep it on the same Gmail thread.
    thread_id: str | None = None
    if draft["thread_email_id"] is not None:
        thread_result = await db.execute(
            text("SELECT thread_id FROM emails WHERE id = :id"),
            {"id": draft["thread_email_id"]},
        )
        thread_row = thread_result.mappings().first()
        thread_id = thread_row["thread_id"] if thread_row else None

    try:
        await gmail_service.send_email(
            db=db,
            account_id=draft["account_id"],
            to_email=draft["to_email"],
            subject=draft["subject"] or "",
            body=draft["body"] or "",
            thread_id=thread_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Sending draft %s failed", draft_id)
        raise HTTPException(status_code=502, detail=f"Failed to send email: {exc}") from exc

    # Record the sent email in Obsidian before returning. Best-effort: a vault
    # write must never fail a send that already succeeded.
    try:
        await embed_sent_email(dict(draft), datetime.utcnow())
    except Exception:  # noqa: BLE001
        logger.exception("Embedding sent draft %s to Obsidian failed", draft_id)

    updated = await db.execute(
        text(
            f"UPDATE drafts SET status = 'sent', updated_at = NOW() "
            f"WHERE id = :id RETURNING {_DRAFT_COLUMNS}"
        ),
        {"id": draft_id},
    )
    # If this draft came from an inbox queue item, mark that item resolved so it
    # drops off the Inbox once its reply has been sent.
    await db.execute(
        text(
            "UPDATE email_queue SET draft_status = 'sent', approved_at = NOW() "
            "WHERE draft_id = :id"
        ),
        {"id": draft_id},
    )
    await db.commit()
    return DraftOut(**dict(updated.mappings().first()))


@router.delete("/{draft_id}")
async def discard_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    """Mark a draft discarded so it drops out of the pending list."""
    result = await db.execute(
        text(
            "UPDATE drafts SET status = 'discarded', updated_at = NOW() "
            "WHERE id = :id RETURNING id"
        ),
        {"id": draft_id},
    )
    if result.first() is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    await db.commit()
    return {"status": "discarded", "id": draft_id}
