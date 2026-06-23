"""Multi-provider AI routing.

One active provider at a time (``ai_providers.is_active``). Anthropic calls go
through the native SDK; every other provider (OpenAI, Gemini, DeepSeek, Ollama)
is reached over its OpenAI-compatible ``/chat/completions`` endpoint via httpx,
so no extra SDK dependencies are needed.

Per-task model selection: chat / classify / draft each pick the active provider's
configured model. API keys are stored encrypted and only decrypted here at call
time — never logged or returned to the frontend.
"""

import logging
from dataclasses import dataclass

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from services import claude_service, crypto, usage_service

logger = logging.getLogger(__name__)
settings = get_settings()

# Default OpenAI-compatible base URLs per provider (used when a row has none).
OPENAI_COMPATIBLE_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "ollama": "http://localhost:11434/v1",
}

# Sensible default models, applied when a provider row leaves a slot blank.
DEFAULT_MODELS = {
    "anthropic": {
        "chat": claude_service.MODEL,
        "classify": claude_service.HAIKU_MODEL,
        "draft": claude_service.MODEL,
    },
    "openai": {"chat": "gpt-4o", "classify": "gpt-4o-mini", "draft": "gpt-4o"},
    "gemini": {
        "chat": "gemini-2.0-flash",
        "classify": "gemini-2.0-flash",
        "draft": "gemini-2.0-flash",
    },
    "deepseek": {"chat": "deepseek-chat", "classify": "deepseek-chat", "draft": "deepseek-chat"},
    "ollama": {"chat": "llama3.1", "classify": "llama3.1", "draft": "llama3.1"},
}


@dataclass
class Usage:
    """Token usage normalized across providers."""

    input_tokens: int = 0
    output_tokens: int = 0


async def get_active(db: AsyncSession) -> dict | None:
    """Return the active provider's config with its key decrypted, or None.

    Falls back to None when no provider is marked active (callers then use the
    Anthropic environment defaults).
    """
    result = await db.execute(
        text(
            """
            SELECT provider, api_key, base_url, model_chat, model_classify, model_draft
            FROM ai_providers WHERE is_active = TRUE LIMIT 1
            """
        )
    )
    row = result.mappings().first()
    if not row:
        return None

    api_key = None
    if row["api_key"]:
        try:
            api_key = crypto.decrypt(row["api_key"])
        except Exception:  # noqa: BLE001 — bad/rotated SECRET_KEY shouldn't crash chat
            logger.error("Failed to decrypt API key for provider %s", row["provider"])

    return {
        "provider": row["provider"],
        "api_key": api_key,
        "base_url": row["base_url"],
        "model_chat": row["model_chat"],
        "model_classify": row["model_classify"],
        "model_draft": row["model_draft"],
    }


def _model_for(active: dict | None, task: str) -> str:
    """Resolve the model for a task from the active provider (or anthropic default)."""
    provider = active["provider"] if active else "anthropic"
    configured = active.get(f"model_{task}") if active else None
    return configured or DEFAULT_MODELS.get(provider, DEFAULT_MODELS["anthropic"])[task]


async def _complete(
    db: AsyncSession,
    *,
    task: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
) -> tuple[str, Usage]:
    """Route a completion to the active provider and return (text, usage)."""
    active = await get_active(db)
    provider = active["provider"] if active else "anthropic"
    model = _model_for(active, task)

    if provider == "anthropic":
        text_out, usage = await _anthropic_complete(active, model, system, messages, max_tokens)
    else:
        text_out, usage = await _openai_compatible_complete(
            active, provider, model, system, messages, max_tokens
        )

    await usage_service.log_usage(provider, model, "input_tokens", usage.input_tokens, db)
    await usage_service.log_usage(provider, model, "output_tokens", usage.output_tokens, db)
    return text_out, usage


async def _anthropic_complete(
    active: dict | None, model: str, system: str, messages: list[dict], max_tokens: int
) -> tuple[str, Usage]:
    key = (active and active["api_key"]) or settings.anthropic_api_key
    client = AsyncAnthropic(api_key=key)
    create_kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        create_kwargs["system"] = system
    response = await client.messages.create(**create_kwargs)
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return claude_service.extract_text(response), usage


async def _openai_compatible_complete(
    active: dict | None,
    provider: str,
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
) -> tuple[str, Usage]:
    base_url = (active and active["base_url"]) or OPENAI_COMPATIBLE_BASE_URLS[provider]
    key = active["api_key"] if active else None

    # OpenAI schema carries the system prompt as a leading system-role message.
    payload_messages = ([{"role": "system", "content": system}] if system else []) + messages
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={"model": model, "messages": payload_messages, "max_tokens": max_tokens},
        )
        response.raise_for_status()
        data = response.json()

    reply = data["choices"][0]["message"]["content"].strip()
    usage_obj = data.get("usage") or {}
    usage = Usage(
        input_tokens=int(usage_obj.get("prompt_tokens", 0)),
        output_tokens=int(usage_obj.get("completion_tokens", 0)),
    )
    return reply, usage


# --- Task entry points -----------------------------------------------------


async def call_chat(
    db: AsyncSession, *, system: str, messages: list[dict], max_tokens: int = 2048
) -> tuple[str, Usage]:
    """Chat completion via the active provider's chat model."""
    return await _complete(db, task="chat", system=system, messages=messages, max_tokens=max_tokens)


async def call_draft(
    db: AsyncSession, *, system: str, messages: list[dict], max_tokens: int = 1024
) -> tuple[str, Usage]:
    """Drafting completion via the active provider's draft model."""
    return await _complete(db, task="draft", system=system, messages=messages, max_tokens=max_tokens)


async def call_classify(
    db: AsyncSession, prompt: str, *, max_tokens: int = 10, system: str = ""
) -> str:
    """Classification/extraction completion via the active provider's classify model."""
    reply, _ = await _complete(
        db,
        task="classify",
        system=system,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return reply


# --- Provider management (for the settings UI) -----------------------------


async def list_providers(db: AsyncSession) -> list[dict]:
    """Return every provider with keys MASKED — never expose decrypted keys.

    Anthropic is special-cased: when no key is stored in the database but
    ``ANTHROPIC_API_KEY`` is present in the environment, it still reports as
    configured (``key_source = "env"``) so the UI doesn't show "not set" for a
    provider that actually works out of the box.
    """
    result = await db.execute(
        text(
            """
            SELECT provider, api_key, base_url, is_active,
                   model_chat, model_classify, model_draft
            FROM ai_providers ORDER BY provider
            """
        )
    )
    providers = []
    seen = set()
    for row in result.mappings().all():
        seen.add(row["provider"])
        stored_key = bool(row["api_key"])
        env_key = row["provider"] == "anthropic" and bool(settings.anthropic_api_key)
        providers.append(
            {
                "provider": row["provider"],
                "has_key": stored_key or env_key,
                "key_source": "configured" if stored_key else ("env" if env_key else None),
                "base_url": row["base_url"],
                "is_active": row["is_active"],
                "model_chat": row["model_chat"],
                "model_classify": row["model_classify"],
                "model_draft": row["model_draft"],
            }
        )

    # Surface Anthropic from the environment even when it has no DB row yet.
    if "anthropic" not in seen and settings.anthropic_api_key:
        providers.append(
            {
                "provider": "anthropic",
                "has_key": True,
                "key_source": "env",
                "base_url": None,
                "is_active": False,
                "model_chat": None,
                "model_classify": None,
                "model_draft": None,
            }
        )
    return providers


async def upsert_provider(
    db: AsyncSession,
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model_chat: str | None = None,
    model_classify: str | None = None,
    model_draft: str | None = None,
    activate: bool = False,
) -> None:
    """Create or update a provider row. Only non-None fields are written.

    The API key is encrypted before storage. Activating a provider deactivates
    all others so exactly one stays active.
    """
    encrypted_key = crypto.encrypt(api_key) if api_key else None

    # Ensure the row exists so subsequent UPDATEs apply cleanly.
    await db.execute(
        text(
            """
            INSERT INTO ai_providers (provider) VALUES (:provider)
            ON CONFLICT (provider) DO NOTHING
            """
        ),
        {"provider": provider},
    )

    sets = ["updated_at = NOW()"]
    params: dict = {"provider": provider}
    if encrypted_key is not None:
        sets.append("api_key = :api_key")
        params["api_key"] = encrypted_key
    if base_url is not None:
        sets.append("base_url = :base_url")
        params["base_url"] = base_url
    if model_chat is not None:
        sets.append("model_chat = :model_chat")
        params["model_chat"] = model_chat
    if model_classify is not None:
        sets.append("model_classify = :model_classify")
        params["model_classify"] = model_classify
    if model_draft is not None:
        sets.append("model_draft = :model_draft")
        params["model_draft"] = model_draft

    await db.execute(
        text(f"UPDATE ai_providers SET {', '.join(sets)} WHERE provider = :provider"),
        params,
    )

    if activate:
        await db.execute(text("UPDATE ai_providers SET is_active = (provider = :provider)"),
                         {"provider": provider})

    await db.commit()


async def delete_key(db: AsyncSession, provider: str) -> None:
    """Remove a provider's stored API key."""
    await db.execute(
        text("UPDATE ai_providers SET api_key = NULL, updated_at = NOW() WHERE provider = :provider"),
        {"provider": provider},
    )
    await db.commit()
