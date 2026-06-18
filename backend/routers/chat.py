"""Chat routes: Claude conversation with calendar context and token tracking."""

import asyncio
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from models.chat import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    TokensToday,
    TokenUsage,
)
from services import calendar_service, claude_service, gmail_service, obsidian_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/chat", tags=["chat"])

HISTORY_LIMIT = 10


async def _calendar_context(db: AsyncSession) -> str:
    """Build a combined calendar block for all connected accounts.

    Fetches today's events and upcoming events (next 7 days) across every
    linked account. Returns empty string when there are no accounts or events
    so nothing leaks into the system prompt.
    """
    try:
        accounts = await gmail_service.list_accounts(db)
    except Exception:
        return ""
    if not accounts:
        return ""

    today = date.today()
    today_lines: list[str] = []
    upcoming_lines: list[str] = []

    for account in accounts:
        try:
            today_events = await calendar_service.get_today(account["id"], db)
            upcoming_events = await calendar_service.get_upcoming(account["id"], db)
        except Exception:
            continue

        for event in today_events:
            start = event["start_time"]
            end = event["end_time"]
            title = event["title"] or "(untitled)"
            if start and end:
                s = start.strftime("%I:%M %p").lstrip("0")
                e = end.strftime("%I:%M %p").lstrip("0")
                today_lines.append(f"- {s} – {e}: {title}")
            elif start:
                today_lines.append(f"- {start.strftime('%I:%M %p').lstrip('0')}: {title}")
            else:
                today_lines.append(f"- {title}")

        for event in upcoming_events:
            start = event["start_time"]
            title = event["title"] or "(untitled)"
            # Exclude events already shown in today's block.
            if start and start.date() > today:
                upcoming_lines.append(f"- {start.strftime('%B %-d')}: {title}")

    if not today_lines and not upcoming_lines:
        return ""

    parts: list[str] = []
    if today_lines:
        parts.append(
            f"CALENDAR (today, {today.strftime('%B %-d')}):\n" + "\n".join(today_lines)
        )
    if upcoming_lines:
        parts.append("UPCOMING (next 7 days):\n" + "\n".join(upcoming_lines))
    return "\n\n".join(parts)


async def _recent_history(db: AsyncSession) -> list[dict]:
    """Return the last HISTORY_LIMIT messages, oldest first, starting with a user turn."""
    result = await db.execute(
        text(
            "SELECT role, content FROM chat_messages ORDER BY id DESC LIMIT :limit"
        ),
        {"limit": HISTORY_LIMIT},
    )
    history = [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(result.mappings().all())
    ]
    # The Messages API requires the first message to be from the user.
    while history and history[0]["role"] != "user":
        history.pop(0)
    return history


@router.post("/message", response_model=ChatResponse)
async def send_message(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Send a user message to Claude and persist the exchange + token usage."""
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")

    calendar_context = await _calendar_context(db)
    obsidian_context = await obsidian_service.get_obsidian_context(payload.message, db)
    system = claude_service.build_system_prompt(
        calendar_context=calendar_context, obsidian_context=obsidian_context
    )

    messages = await _recent_history(db)
    messages.append({"role": "user", "content": payload.message})

    try:
        reply, usage = await claude_service.chat(system=system, messages=messages)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Claude chat request failed")
        raise HTTPException(status_code=502, detail=f"Claude request failed: {exc}") from exc

    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    total = input_tokens + output_tokens

    await db.execute(
        text(
            "INSERT INTO chat_messages (role, content, tokens_used) "
            "VALUES ('user', :content, NULL)"
        ),
        {"content": payload.message},
    )
    await db.execute(
        text(
            "INSERT INTO chat_messages (role, content, tokens_used) "
            "VALUES ('assistant', :content, :tokens)"
        ),
        {"content": reply, "tokens": total},
    )

    # Accumulate today's usage rather than overwriting it.
    await db.execute(
        text(
            """
            INSERT INTO token_usage (session_date, input_tokens, output_tokens, total_tokens, updated_at)
            VALUES (CURRENT_DATE, :input, :output, :total, NOW())
            ON CONFLICT (session_date) DO UPDATE SET
                input_tokens = token_usage.input_tokens + EXCLUDED.input_tokens,
                output_tokens = token_usage.output_tokens + EXCLUDED.output_tokens,
                total_tokens = token_usage.total_tokens + EXCLUDED.total_tokens,
                updated_at = NOW()
            """
        ),
        {"input": input_tokens, "output": output_tokens, "total": total},
    )
    await db.commit()

    # Mirror the exchange into the Obsidian daily note (best-effort, no vault → no-op).
    try:
        await asyncio.to_thread(obsidian_service.append_exchange, payload.message, reply)
    except Exception:  # noqa: BLE001 — never fail a chat over a note write
        logger.exception("Obsidian daily-note append failed")

    return ChatResponse(
        response=reply,
        tokens=TokenUsage(input=input_tokens, output=output_tokens, total=total),
    )


@router.get("/messages", response_model=list[ChatMessageOut])
async def get_messages(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return the most recent messages, oldest first, to pre-load on page load."""
    result = await db.execute(
        text(
            "SELECT role, content, created_at "
            "FROM chat_messages ORDER BY id DESC LIMIT :limit"
        ),
        {"limit": limit},
    )
    rows = list(reversed(result.mappings().all()))
    return [
        ChatMessageOut(
            role=row["role"], content=row["content"], created_at=row["created_at"]
        )
        for row in rows
    ]


@router.get("/tokens/today", response_model=TokensToday)
async def tokens_today(db: AsyncSession = Depends(get_db)):
    """Return today's accumulated token usage."""
    result = await db.execute(
        text(
            "SELECT input_tokens, output_tokens, total_tokens "
            "FROM token_usage WHERE session_date = CURRENT_DATE"
        )
    )
    row = result.mappings().first()
    if row is None:
        return TokensToday(total=0, input=0, output=0)
    return TokensToday(
        total=row["total_tokens"],
        input=row["input_tokens"],
        output=row["output_tokens"],
    )
