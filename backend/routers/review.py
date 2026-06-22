"""Daily Review routes: serve, approve, dismiss, and manually trigger the
afternoon email review.

The afternoon review task triages the day's pending emails and stores the result
in ``afternoon_reviews``. Approving here is the ONLY point where those triage
classifications are pushed to Gmail — nothing is applied automatically.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import obsidian_service, triage_service
from services.tasks import get_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])


class ReviewApprovePayload(BaseModel):
    """Per-email classification overrides chosen by the user in the Review UI.

    Keys are email_id values (as strings — JSON object keys are always strings);
    values are the final classification the user selected ('keep', 'archive',
    'trash'). Any email_id not present here keeps the auto-triage classification
    stored in afternoon_reviews.emails_json.
    """

    overrides: dict[str, str] = {}


async def _today_review(db: AsyncSession) -> dict | None:
    """Return today's review row as a dict, or None if it hasn't run yet."""
    result = await db.execute(
        text(
            """
            SELECT review_date, emails_json, status, approved_at, updated_at
            FROM afternoon_reviews
            WHERE review_date = CURRENT_DATE
            """
        )
    )
    row = result.mappings().first()
    if not row:
        return None
    return {
        "review_date": row["review_date"].isoformat(),
        "emails": row["emails_json"] or [],
        "status": row["status"],
        "approved_at": row["approved_at"].isoformat() if row["approved_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.get("/today")
async def get_today_review(db: AsyncSession = Depends(get_db)):
    """Return today's afternoon review, or ``{review: null}`` if not run yet."""
    return {"review": await _today_review(db)}


@router.get("/trigger")
async def trigger_review(db: AsyncSession = Depends(get_db)):
    """Manually run the afternoon review now (used for testing / on-demand)."""
    task = get_task("afternoon_review")
    if not task:
        raise HTTPException(status_code=500, detail="Afternoon review task not registered")
    result = await task.safe_run(db)
    return {"result": result, "review": await _today_review(db)}


@router.post("/approve")
async def approve_review(
    payload: ReviewApprovePayload = ReviewApprovePayload(),
    db: AsyncSession = Depends(get_db),
):
    """Apply today's review: push triage to Gmail, save summaries, mark approved.

    The frontend may have reclassified individual emails via dropdowns; those
    are sent as ``payload.overrides`` (email_id → classification) and merged
    on top of the auto-triage result before any Gmail mutations run.

    Queued draft replies already live in the Drafts panel (generated as pending),
    so approval only needs to write each email's classification, apply triage per
    account, and record summaries in Obsidian.
    """
    review = await _today_review(db)
    if not review:
        raise HTTPException(status_code=404, detail="No review for today")

    emails = list(review["emails"])  # shallow copy so we can mutate safely

    # Apply user overrides on top of the stored auto-triage classifications.
    if payload.overrides:
        for item in emails:
            key = str(item.get("email_id", ""))
            if key in payload.overrides:
                item["classification"] = payload.overrides[key]

    # Write each reviewed email's classification into emails.triage_status, and
    # collect the accounts involved so triage can be applied per account.
    changes: list[tuple[int, str]] = []
    account_ids: set[int] = set()
    for item in emails:
        if item.get("email_id") and item.get("classification"):
            changes.append((item["email_id"], item["classification"]))
    if changes:
        await triage_service.bulk_update_triage_status(db, changes)

    # Look up the accounts for the reviewed emails.
    if emails:
        ids = [e["email_id"] for e in emails if e.get("email_id")]
        if ids:
            rows = await db.execute(
                text("SELECT DISTINCT account_id FROM emails WHERE id = ANY(:ids)"),
                {"ids": ids},
            )
            account_ids = {row[0] for row in rows.all()}

    applied = {"trashed": 0, "archived": 0}
    for account_id in account_ids:
        try:
            result = await triage_service.apply_triage(account_id, db)
            applied["trashed"] += result.get("trashed", 0)
            applied["archived"] += result.get("archived", 0)
        except Exception:  # noqa: BLE001 — one account failing shouldn't abort the rest
            logger.exception("Failed to apply triage for account %s", account_id)

    # Save kept/archived summaries to the daily note (skip trashed).
    summaries = [
        {"subject": e.get("subject"), "from": e.get("from"), "summary": e.get("summary")}
        for e in emails
        if e.get("classification") != "trash"
    ]
    await obsidian_service.append_review_summaries(summaries)

    await db.execute(
        text(
            """
            UPDATE afternoon_reviews
            SET status = 'approved', approved_at = NOW(), updated_at = NOW()
            WHERE review_date = CURRENT_DATE
            """
        )
    )
    await db.commit()

    return {"status": "approved", "applied": applied, "review": await _today_review(db)}


@router.post("/reopen")
async def reopen_review(db: AsyncSession = Depends(get_db)):
    """Set today's dismissed review back to pending so the user can act on it."""
    result = await db.execute(
        text(
            """
            UPDATE afternoon_reviews
            SET status = 'pending', updated_at = NOW()
            WHERE review_date = CURRENT_DATE
            RETURNING id
            """
        )
    )
    if not result.first():
        raise HTTPException(status_code=404, detail="No review for today")
    await db.commit()
    return {"status": "pending", "review": await _today_review(db)}


@router.post("/dismiss")
async def dismiss_review(db: AsyncSession = Depends(get_db)):
    """Mark today's review dismissed without applying any action."""
    result = await db.execute(
        text(
            """
            UPDATE afternoon_reviews
            SET status = 'dismissed', updated_at = NOW()
            WHERE review_date = CURRENT_DATE
            RETURNING id
            """
        )
    )
    if not result.first():
        raise HTTPException(status_code=404, detail="No review for today")
    await db.commit()
    return {"status": "dismissed", "review": await _today_review(db)}
