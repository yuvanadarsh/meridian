"""Chat routes: Claude conversation with calendar context and token tracking."""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import get_db
from models.chat import ChatRequest, ChatResponse, TokensToday, TokenUsage
from services import calendar_service, claude_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/chat", tags=["chat"])

HISTORY_LIMIT = 10


async def _calendar_context(account_id: int | None, db: AsyncSession) -> str:
    """A compact summary of today's events, or empty string if none/no account."""
    if account_id is None:
        return ""
    events = await calendar_service.get_today(account_id, db)
    if not events:
        return ""
    lines = []
    for event in events:
        start = event["start_time"].strftime("%H:%M") if event["start_time"] else "--:--"
        lines.append(f"- {start} {event['title'] or '(untitled)'}")
    return "Today's calendar:\n" + "\n".join(lines)


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

    system = (
        "You are Meridian, a personal AI assistant. You help the user manage their "
        "email, calendar, and daily tasks. Be concise, direct, and helpful. "
        f"Today is {date.today().isoformat()}."
    )
    context = await _calendar_context(payload.account_id, db)
    if context:
        system += "\n\n" + context

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

    return ChatResponse(
        response=reply,
        tokens=TokenUsage(input=input_tokens, output=output_tokens, total=total),
    )


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
