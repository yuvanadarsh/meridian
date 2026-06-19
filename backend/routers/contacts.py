"""Contact intelligence routes: build the contact graph and query contacts."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import contact_service, gmail_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.post("/build/{account_id}")
async def build_contact_graph(
    account_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Build the contact graph from an account's email history (background task)."""
    accounts = await gmail_service.list_accounts(db)
    if not any(account["id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="Account not found")
    background_tasks.add_task(
        contact_service.run_build_contact_graph_background, account_id
    )
    return {"status": "started", "account_id": account_id}


@router.get("")
async def list_contacts(
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Return all contacts sorted by email volume, most active first."""
    return {"contacts": await contact_service.list_contacts(db, limit=limit)}


@router.get("/search")
async def search_contacts(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    """Search contacts by name or email."""
    return {"contacts": await contact_service.search_contacts(db, q)}
