"""Persistent chat routes — long-lived conversations that survive the daily reset.

Unlike ``/chat`` (which only keeps today's messages), these conversations are
stored forever, listed on the /chat page, and mirrored into the memory layer
under a ``Chats/{title}`` note. Each message reuses the exact same RAG context
and system-prompt builder as the daily chat so answers stay consistent.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from routers.chat import _DEEP_PHRASES, _calendar_context, _get_context_tiered
from services import (
    claude_service,
    contact_service,
    gmail_service,
    memory_service,
    provider_service,
    settings_service,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/persistent-chats", tags=["persistent-chats"])

# How many prior messages to feed the model as conversation context.
CONTEXT_MESSAGE_LIMIT = 20


class TitlePatch(BaseModel):
    title: str


class MessageIn(BaseModel):
    content: str


async def _get_chat(chat_id: str, db: AsyncSession) -> dict:
    """Fetch a chat row by id or raise 404."""
    result = await db.execute(
        text(
            """
            SELECT id, title, auto_titled, created_at, updated_at
            FROM persistent_chats WHERE id = :id
            """
        ),
        {"id": chat_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return dict(row)


async def _generate_title(db: AsyncSession, first_user_message: str) -> str | None:
    """Ask the active provider's classify model for a short conversation title."""
    prompt = (
        "Generate a 4-6 word title for a conversation that starts with: "
        f"{first_user_message}. Return only the title, no quotes."
    )
    try:
        raw = await provider_service.call_classify(db, prompt, max_tokens=30)
    except Exception:  # noqa: BLE001 — a failed title shouldn't break the chat
        logger.exception("Persistent-chat title generation failed")
        return None
    title = raw.strip().strip('"').strip()
    return title[:255] or None


@router.get("")
async def list_chats(db: AsyncSession = Depends(get_db)):
    """List all persistent chats, most recently updated first."""
    result = await db.execute(
        text(
            """
            SELECT id, title, auto_titled, created_at, updated_at
            FROM persistent_chats
            ORDER BY updated_at DESC
            """
        )
    )
    return {"chats": [dict(row) for row in result.mappings().all()]}


@router.post("")
async def create_chat(db: AsyncSession = Depends(get_db)):
    """Create an empty chat (no title yet) and return its id."""
    result = await db.execute(
        text(
            """
            INSERT INTO persistent_chats DEFAULT VALUES
            RETURNING id, title, auto_titled, created_at, updated_at
            """
        )
    )
    row = result.mappings().first()
    await db.commit()
    return dict(row)


@router.get("/{chat_id}")
async def get_chat(chat_id: str, db: AsyncSession = Depends(get_db)):
    """Return a chat with all of its messages, oldest first."""
    chat = await _get_chat(chat_id, db)
    result = await db.execute(
        text(
            """
            SELECT role, content, created_at
            FROM persistent_chat_messages
            WHERE chat_id = :id
            ORDER BY id ASC
            """
        ),
        {"id": chat_id},
    )
    chat["messages"] = [dict(row) for row in result.mappings().all()]
    return chat


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a chat and its messages. The memory note is left untouched."""
    await _get_chat(chat_id, db)
    await db.execute(
        text("DELETE FROM persistent_chats WHERE id = :id"), {"id": chat_id}
    )
    await db.commit()
    return {"deleted": True, "id": chat_id}


@router.patch("/{chat_id}/title")
async def rename_chat(chat_id: str, payload: TitlePatch, db: AsyncSession = Depends(get_db)):
    """Rename a chat. Sets auto_titled so the title isn't overwritten later."""
    await _get_chat(chat_id, db)
    title = payload.title.strip()[:255]
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    await db.execute(
        text(
            """
            UPDATE persistent_chats
            SET title = :title, auto_titled = TRUE, updated_at = NOW()
            WHERE id = :id
            """
        ),
        {"title": title, "id": chat_id},
    )
    await db.commit()
    return {"id": chat_id, "title": title}


@router.post("/{chat_id}/messages")
async def send_message(chat_id: str, payload: MessageIn, db: AsyncSession = Depends(get_db)):
    """Send a message to a persistent chat and return the assistant's reply.

    Uses the same tiered RAG context and system-prompt builder as the daily chat.
    On the first exchange, auto-generates a title and creates the Obsidian note;
    subsequent exchanges are appended to that note.
    """
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")

    chat = await _get_chat(chat_id, db)
    user_message = payload.content.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Count existing messages to detect the first exchange (for titling/note creation).
    count_result = await db.execute(
        text("SELECT COUNT(*) AS n FROM persistent_chat_messages WHERE chat_id = :id"),
        {"id": chat_id},
    )
    is_first_exchange = (count_result.scalar() or 0) == 0

    # Persist the user message.
    await db.execute(
        text(
            "INSERT INTO persistent_chat_messages (chat_id, role, content) "
            "VALUES (:id, 'user', :content)"
        ),
        {"id": chat_id, "content": user_message},
    )
    await db.commit()

    # Build conversation history (last N messages, oldest first, starting on a user turn).
    history_result = await db.execute(
        text(
            """
            SELECT role, content FROM persistent_chat_messages
            WHERE chat_id = :id
            ORDER BY id DESC
            LIMIT :limit
            """
        ),
        {"id": chat_id, "limit": CONTEXT_MESSAGE_LIMIT},
    )
    history = [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(history_result.mappings().all())
    ]
    while history and history[0]["role"] != "user":
        history.pop(0)

    # Same RAG context as the daily chat: calendar + Obsidian + tiered email + contacts.
    try:
        accounts = await gmail_service.list_accounts(db)
    except Exception:  # noqa: BLE001
        accounts = []

    calendar_context = await _calendar_context(db)
    memory_context = await memory_service.get_general_context(user_message, db)
    tier = 2 if any(p in user_message.lower() for p in _DEEP_PHRASES) else 1
    email_context, context_source = await _get_context_tiered(user_message, db, tier=tier)
    contact_context = await contact_service.get_contact_context(user_message, db)
    tone = await settings_service.get_value(db, "response_tone")

    system = claude_service.build_system_prompt(
        calendar_context=calendar_context,
        memory_context=memory_context,
        email_context=email_context,
        contact_context=contact_context,
        accounts=accounts,
        tone=tone,
        allow_draft=False,
    )
    if context_source != "none":
        system += f"\nContext source: {context_source}"

    try:
        reply, _usage = await provider_service.call_chat(db, system=system, messages=history)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Persistent chat request to AI provider failed")
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}") from exc

    # Persist the assistant reply and bump updated_at.
    await db.execute(
        text(
            "INSERT INTO persistent_chat_messages (chat_id, role, content) "
            "VALUES (:id, 'assistant', :content)"
        ),
        {"id": chat_id, "content": reply},
    )

    # Auto-generate a title on the first exchange (if not already user-named).
    new_title: str | None = None
    if is_first_exchange and not chat["auto_titled"]:
        new_title = await _generate_title(db, user_message)
        if new_title:
            await db.execute(
                text(
                    """
                    UPDATE persistent_chats
                    SET title = :title, auto_titled = TRUE WHERE id = :id
                    """
                ),
                {"title": new_title, "id": chat_id},
            )

    await db.execute(
        text("UPDATE persistent_chats SET updated_at = NOW() WHERE id = :id"),
        {"id": chat_id},
    )
    await db.commit()

    # Mirror into the memory layer (best-effort). write_persistent_chat_note
    # appends to the note by title, so the first exchange creates it and later
    # ones extend it.
    try:
        title_for_note = new_title or chat["title"] or "Untitled conversation"
        await memory_service.write_persistent_chat_note(
            chat_id=str(chat_id),
            title=title_for_note,
            user_message=user_message,
            assistant_message=reply,
            db=db,
        )
    except Exception:  # noqa: BLE001 — never fail a chat over a note write
        logger.exception("Persistent-chat memory mirror failed")

    return {"content": reply, "title": new_title}
