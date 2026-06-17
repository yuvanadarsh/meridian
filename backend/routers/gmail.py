"""Gmail routes: OAuth, account management, sweep, and triage.

OAuth lives here now; the sweep and triage routes are added in later steps.
"""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from services import gmail_service

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


@router.post("/sweep/{account_id}")
async def start_sweep(
    account_id: int,
    background_tasks: BackgroundTasks,
    max_messages: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """Kick off an email sweep for an account as a background task."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(gmail_service.run_sweep_background, account_id, max_messages)
    return {"status": "started", "account_id": account_id}


@router.get("/sweep/progress/{account_id}")
async def sweep_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return the current sweep progress for an account."""
    return await gmail_service.get_sweep_progress(db, account_id)
