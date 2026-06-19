"""Supercharge routes: upload AI chat exports, parse into Obsidian, track progress."""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import obsidian_service, supercharge_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supercharge", tags=["supercharge"])

# Reject absurdly large uploads early (50 MB matches the typical export ceiling).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post("/upload")
async def upload_export(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Upload a Claude/ChatGPT/Gemini export JSON; parse + vectorize in the background."""
    if obsidian_service.vault_path() is None:
        raise HTTPException(
            status_code=400,
            detail="OBSIDIAN_VAULT_PATH is not configured — set it before importing.",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB).")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    provider, conversations = await supercharge_service.parse_export(data)
    if not conversations:
        raise HTTPException(
            status_code=400, detail="No conversations found in the uploaded file."
        )

    import_id = await supercharge_service.create_import(
        db, provider, file.filename or "export.json", len(conversations)
    )
    background_tasks.add_task(
        supercharge_service.process_import, import_id, provider, conversations
    )
    return {
        "import_id": import_id,
        "provider": provider,
        "total_conversations": len(conversations),
    }


@router.get("/progress/{import_id}")
async def import_progress(import_id: int, db: AsyncSession = Depends(get_db)):
    """Return the processing status for an import."""
    progress = await supercharge_service.get_progress(db, import_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return progress


@router.get("")
async def list_imports(db: AsyncSession = Depends(get_db)):
    """Return all past imports, newest first."""
    return {"imports": await supercharge_service.list_imports(db)}
