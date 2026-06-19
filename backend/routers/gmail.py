"""Gmail routes: OAuth, account management, sweep, and triage.

OAuth lives here now; the sweep and triage routes are added in later steps.
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from models.gmail import AccountUpdate, BulkTriageRequest, SweepOptions, TriageApproval
from services import gmail_service, thread_service, triage_service, vector_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/gmail", tags=["gmail"])


@router.get("/auth")
async def gmail_auth(
    label: str = Query(..., description="Account role: personal, school, work, professional"),
):
    """Return the Google OAuth consent URL for connecting an account."""
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500, detail="Google OAuth credentials are not configured"
        )
    try:
        url = gmail_service.build_auth_url(label)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build OAuth URL")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"url": url}


@router.get("/callback")
async def gmail_callback(
    code: str = Query(...),
    state: str = Query("personal", description="Account label, passed through OAuth state"),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth redirect: exchange the code, store the token, return to UI."""
    try:
        # The Google client calls are blocking — keep them off the event loop.
        creds = await asyncio.to_thread(gmail_service.exchange_code, code)
        email = await asyncio.to_thread(gmail_service.get_account_email, creds)
        await gmail_service.upsert_account(
            db,
            email=email,
            label=state,
            token=gmail_service.credentials_to_dict(creds),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("OAuth callback failed")
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {exc}") from exc

    logger.info("Connected account %s as '%s'", email, state)
    return RedirectResponse(url=f"{settings.frontend_url}/?connected={email}")


@router.get("/accounts")
async def gmail_accounts(db: AsyncSession = Depends(get_db)):
    """List connected Gmail accounts."""
    return await gmail_service.list_accounts(db)


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Rename an account's label."""
    updated = await gmail_service.update_account_label(db, account_id, payload.label)
    if updated is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return updated


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    """Remove an account and all of its emails and calendar events."""
    deleted = await gmail_service.delete_account(db, account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": True}


@router.get("/estimate/{account_id}")
async def estimate(account_id: int, db: AsyncSession = Depends(get_db)):
    """Approximate how many messages the mailbox holds (for the sweep options UI)."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        count = await gmail_service.estimate_count(db, account_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to estimate mailbox size for account %s", account_id)
        raise HTTPException(status_code=502, detail=f"Estimate failed: {exc}") from exc
    return {"estimated_count": count}


@router.post("/sweep/{account_id}")
async def start_sweep(
    account_id: int,
    options: SweepOptions,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Kick off an email sweep for an account as a background task."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(
        gmail_service.run_sweep_background,
        account_id,
        mode=options.mode,
        count=options.count,
        since_date=options.since_date,
    )
    return {"status": "started", "account_id": account_id}


@router.get("/sweep/progress/{account_id}")
async def sweep_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return the current sweep progress for an account."""
    return await gmail_service.get_sweep_progress(db, account_id)


@router.post("/triage/start/{account_id}")
async def start_triage(
    account_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Classify all pending emails for an account (background task)."""
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(triage_service.run_triage_background, account_id)
    return {"status": "started", "account_id": account_id}


@router.get("/triage/results/{account_id}")
async def triage_results(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return triage counts and a sample of emails per category for review."""
    return await triage_service.get_triage_results(account_id, db)


@router.get("/triage/emails/{account_id}")
async def triage_emails(
    account_id: int,
    status: str = Query(..., pattern="^(trash|archive|keep|unreadable)$"),
    limit: int = Query(50, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Return one page of emails in a triage category (with AI summaries)."""
    return await triage_service.get_triage_emails(account_id, db, status, limit, offset)


@router.get("/triage/report/{account_id}", response_class=PlainTextResponse)
async def triage_report(account_id: int, db: AsyncSession = Depends(get_db)):
    """Plain-text report of every triaged email, grouped by category."""
    return await triage_service.build_triage_report(account_id, db)


@router.post("/triage/discard/{account_id}")
async def discard_sweep(account_id: int, db: AsyncSession = Depends(get_db)):
    """Discard an account's swept emails locally (Gmail untouched)."""
    return await triage_service.discard_sweep(account_id, db)


@router.post("/triage/approve/{account_id}")
async def approve_triage(
    account_id: int,
    payload: TriageApproval,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Apply approved triage to Gmail, then start vectorizing keep/archive emails.

    The ONLY endpoint that mutates Gmail.
    """
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    overrides = [{"id": item.id, "status": item.status} for item in payload.overrides]
    try:
        result = await triage_service.apply_triage(account_id, db, overrides=overrides)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to apply triage for account %s", account_id)
        raise HTTPException(status_code=500, detail=f"Failed to apply triage: {exc}") from exc
    # Build memory from the surviving keep + archive emails, then group into threads.
    background_tasks.add_task(vector_service.run_vectorize_background, account_id)
    background_tasks.add_task(thread_service.run_build_threads_background, account_id)
    return result


@router.patch("/emails/triage/bulk")
async def bulk_update_triage(
    payload: BulkTriageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist user reclassifications from the triage review UI without applying to Gmail.

    This is a save-draft operation: it updates ``triage_status`` in the local
    database so the review survives a refresh, but does not trash/archive
    anything in Gmail — that happens on approval.
    """
    if not payload.changes:
        return {"updated": 0}
    updated = await triage_service.bulk_update_triage_status(
        db, [(c.email_id, c.triage_status) for c in payload.changes]
    )
    return {"updated": updated}


async def _vectorize_and_build_threads(account_id: int) -> None:
    """Run vectorization then thread build sequentially in a single background task."""
    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            await vector_service.vectorize_account(account_id, db)
            await thread_service.build_threads(account_id, db)
        except Exception:  # noqa: BLE001
            logger.exception("vectorize+build_threads failed for account %s", account_id)


@router.post("/vectorize/{account_id}")
async def start_vectorize(
    account_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Embed an account's keep/archive emails, then build threads (background task)."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(_vectorize_and_build_threads, account_id)
    return {"status": "started", "account_id": account_id}


@router.get("/vectorize/progress/{account_id}")
async def vectorize_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return how many keep/archive emails have been embedded so far."""
    return await vector_service.vectorize_progress(account_id, db)


@router.post("/threads/build/{account_id}")
async def build_threads(
    account_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Group an account's emails into conversation threads (background task)."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(thread_service.run_build_threads_background, account_id)
    return {"status": "started", "account_id": account_id}


@router.get("/threads/build/progress/{account_id}")
async def build_threads_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return ``{processed, total}`` for an account's thread build."""
    return await thread_service.build_progress(account_id, db)


@router.get("/threads/count/{account_id}")
async def thread_count(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return ``{processed, total}`` — built threads vs distinct thread_ids (alias of build progress)."""
    return await thread_service.build_progress(account_id, db)
