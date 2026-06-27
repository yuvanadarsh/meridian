"""Gmail routes: OAuth, account management, sweep, and triage."""

import asyncio
import json
import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from models.gmail import AccountUpdate, BulkTriageRequest, SweepOptions, TriageApproval
from services import gmail_service, obsidian_service, thread_service, triage_service, vector_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/gmail", tags=["gmail"])


@router.get("/auth")
async def gmail_auth(
    label: str = Query(..., description="Account role: personal, school, work, professional"),
    db: AsyncSession = Depends(get_db),
):
    """Return the Google OAuth consent URL for connecting an account.

    Generates a PKCE code verifier and persists it in ``oauth_state`` keyed
    by a random state token. The callback retrieves the verifier from the
    database — it never lives only in memory.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500, detail="Google OAuth credentials are not configured"
        )
    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = gmail_service.generate_pkce_pair()
    try:
        await db.execute(
            text(
                "INSERT INTO oauth_state (state, code_verifier, label) "
                "VALUES (:state, :verifier, :label)"
            ),
            {"state": state, "verifier": code_verifier, "label": label},
        )
        await db.commit()
        url = gmail_service.build_auth_url(label, state, code_challenge)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to build OAuth URL")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"url": url}


@router.get("/reauth/{account_id}")
async def reauth_account(account_id: int, db: AsyncSession = Depends(get_db)):
    """Start a re-authentication flow for an existing account.

    Preserves all swept emails and account data — only the OAuth token is
    refreshed. On callback the existing ``gmail_accounts`` row is updated
    (not replaced), and ``auth_status`` is reset to ``'ok'``.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=500, detail="Google OAuth credentials are not configured"
        )
    result = await db.execute(
        text("SELECT id, email, label FROM gmail_accounts WHERE id = :id"),
        {"id": account_id},
    )
    account = result.mappings().first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = gmail_service.generate_pkce_pair()
    await db.execute(
        text(
            "INSERT INTO oauth_state (state, code_verifier, label, account_id) "
            "VALUES (:state, :verifier, :label, :account_id)"
        ),
        {
            "state": state,
            "verifier": code_verifier,
            "label": account["label"],
            "account_id": account_id,
        },
    )
    await db.commit()
    url = gmail_service.build_auth_url(account["label"] or "", state, code_challenge)
    return RedirectResponse(url=url)


@router.get("/callback")
async def gmail_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth redirect: exchange the code, store the token, return to UI.

    Retrieves the PKCE code verifier from ``oauth_state`` and deletes the row
    immediately after use. If the state carries an ``account_id`` this is a
    re-auth: the existing account's token is updated without touching any data.
    """
    # Retrieve and immediately consume the state row.
    result = await db.execute(
        text(
            "SELECT code_verifier, label, account_id "
            "FROM oauth_state WHERE state = :state"
        ),
        {"state": state},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    code_verifier = row["code_verifier"]
    label = row["label"]
    reauth_account_id = row["account_id"]

    await db.execute(
        text("DELETE FROM oauth_state WHERE state = :state"), {"state": state}
    )
    await db.commit()

    try:
        creds = await asyncio.to_thread(gmail_service.exchange_code, code, code_verifier)
    except Exception as exc:  # noqa: BLE001
        logger.exception("OAuth code exchange failed")
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {exc}") from exc

    if reauth_account_id is not None:
        # Re-auth: update the token on the existing account row.
        token_json = json.dumps(gmail_service.credentials_to_dict(creds))
        await db.execute(
            text(
                "UPDATE gmail_accounts "
                "SET oauth_token = CAST(:token AS jsonb), auth_status = 'ok' "
                "WHERE id = :id"
            ),
            {"token": token_json, "id": reauth_account_id},
        )
        await db.commit()
        logger.info("Re-authenticated account id=%s", reauth_account_id)
        return RedirectResponse(url=f"{settings.frontend_url}/?reauthed=true")

    # New account: look up the email address and upsert.
    try:
        email = await asyncio.to_thread(gmail_service.get_account_email, creds)
        await gmail_service.upsert_account(
            db,
            email=email,
            label=label or "personal",
            token=gmail_service.credentials_to_dict(creds),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("OAuth callback failed")
        raise HTTPException(status_code=400, detail=f"OAuth callback failed: {exc}") from exc

    logger.info("Connected account %s as '%s'", email, label)
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
    # Export threads to Obsidian vault after vectorization and thread build are queued.
    background_tasks.add_task(obsidian_service.export_threads_to_obsidian_background, account_id)
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


@router.post("/threads/export-to-obsidian/{account_id}")
async def export_threads_to_obsidian(
    account_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Write all email threads for an account to the Obsidian vault as linked notes."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(obsidian_service.export_threads_to_obsidian_background, account_id)
    return {"status": "started", "account_id": account_id}


@router.get("/threads/obsidian-export/progress/{account_id}")
async def obsidian_export_progress(account_id: int, db: AsyncSession = Depends(get_db)):
    """Return the Obsidian thread export progress for an account.

    Falls back to counting actual email notes in obsidian_notes so the row
    correctly shows "In Obsidian ✓" for exports done before progress tracking
    was introduced.
    """
    from services import settings_service

    progress_key = f"obsidian_export_progress_{account_id}"
    raw = await settings_service.get_value(db, progress_key)
    if raw:
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass

    # No stored progress — check whether email notes already exist in the vault.
    notes_result = await db.execute(
        text("SELECT count(*) AS count FROM obsidian_notes WHERE file_path LIKE '%/Emails/%'")
    )
    notes_count = notes_result.fetchone().count
    if notes_count > 0:
        return {"processed": notes_count, "total": notes_count, "done": True}
    return {"processed": 0, "total": 0, "done": False}
