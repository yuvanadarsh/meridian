"""User settings persistence — a thin key/value store over ``user_settings``."""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Fallbacks used when a key is missing (e.g. migration not yet run).
DEFAULTS = {
    "response_tone": "concise",
    "voice_enabled": "true",
    "agent_name": "Meridian",
    "triage_mode": "normal",
    "embedding_model": "voyage-3-lite",
}


async def get_all(db: AsyncSession) -> dict[str, str]:
    """Return all settings as a key/value dict, backfilled with defaults."""
    result = await db.execute(text("SELECT key, value FROM user_settings"))
    stored = {row["key"]: row["value"] for row in result.mappings().all()}
    return {**DEFAULTS, **stored}


async def get_value(db: AsyncSession, key: str) -> str:
    """Return one setting's value, or its default when unset."""
    result = await db.execute(
        text("SELECT value FROM user_settings WHERE key = :key"), {"key": key}
    )
    row = result.mappings().first()
    return row["value"] if row else DEFAULTS.get(key, "")


async def set_value(db: AsyncSession, key: str, value: str) -> None:
    """Upsert one setting."""
    await db.execute(
        text(
            """
            INSERT INTO user_settings (key, value, updated_at)
            VALUES (:key, :value, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """
        ),
        {"key": key, "value": value},
    )
    await db.commit()
