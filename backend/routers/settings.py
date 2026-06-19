"""Settings routes: preferences, AI providers, and embedding configuration."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from services import provider_service, settings_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

# Providers we know how to route to (anthropic native + OpenAI-compatible).
KNOWN_PROVIDERS = {"anthropic", "openai", "gemini", "deepseek", "ollama"}


class SettingUpdate(BaseModel):
    """A single key/value setting change."""

    key: str
    value: str


class ProviderUpdate(BaseModel):
    """Partial update for one AI provider — only set fields are applied."""

    api_key: str | None = None
    base_url: str | None = None
    model_chat: str | None = None
    model_classify: str | None = None
    model_draft: str | None = None
    activate: bool = False


@router.get("")
async def get_settings_endpoint(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Return all settings as a key/value object."""
    return await settings_service.get_all(db)


@router.patch("")
async def update_setting(payload: SettingUpdate, db: AsyncSession = Depends(get_db)):
    """Upsert one setting and echo back the full settings object."""
    await settings_service.set_value(db, payload.key, payload.value)
    return await settings_service.get_all(db)


@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    """List all AI providers with API keys MASKED (never returned in plaintext)."""
    return {"providers": await provider_service.list_providers(db)}


@router.patch("/providers/{provider}")
async def update_provider(
    provider: str,
    payload: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Set a provider's key/base_url/models, and optionally make it active."""
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    await provider_service.upsert_provider(
        db,
        provider,
        api_key=payload.api_key,
        base_url=payload.base_url,
        model_chat=payload.model_chat,
        model_classify=payload.model_classify,
        model_draft=payload.model_draft,
        activate=payload.activate,
    )
    return {"providers": await provider_service.list_providers(db)}


@router.delete("/providers/{provider}/key")
async def delete_provider_key(provider: str, db: AsyncSession = Depends(get_db)):
    """Remove a provider's stored API key."""
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    await provider_service.delete_key(db, provider)
    return {"providers": await provider_service.list_providers(db)}
