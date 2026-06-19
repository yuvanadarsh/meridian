"""Chat routes: Claude conversation with calendar context and token tracking."""

import json
import logging
import re
from datetime import date, datetime

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
from services import (
    calendar_service,
    claude_service,
    contact_service,
    digest_service,
    draft_service,
    gmail_service,
    obsidian_service,
    provider_service,
    settings_service,
    vector_service,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/chat", tags=["chat"])

HISTORY_LIMIT = 10

# Phrases that mean "read me my daily brief" instead of a normal chat turn.
_DIGEST_TRIGGERS = (
    "digest",
    "brief",
    "morning brief",
    "what's going on",
    "whats going on",
    "catch me up",
)


def _is_digest_request(message: str) -> bool:
    text_lower = message.lower()
    return any(trigger in text_lower for trigger in _DIGEST_TRIGGERS)


# Only these explicit phrases should put Claude into email-drafting mode. A plain
# question that happens to mention "email", a person, or a subject must NOT trigger
# a draft — that hallucination was the Phase 3 bug this guards against.
DRAFT_TRIGGER_PHRASES = (
    "draft an email",
    "draft a reply",
    "draft me",
    "write an email",
    "compose an email",
    "reply to",
    "send an email",
    "write a message to",
)

# Loose RFC-ish check: a recipient must at least look like local@domain.tld.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_draft_intent(message: str) -> bool:
    """True only when the user explicitly asks to draft/write/send an email.

    Used to decide whether to expose the ``DRAFT_EMAIL:`` action protocol to
    Claude at all. Keeping this strict prevents accidental drafts on questions
    like "what did Max email me about?".
    """
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in DRAFT_TRIGGER_PHRASES)


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


async def _maybe_handle_action(
    reply: str, db: AsyncSession, *, allow_draft: bool = False
) -> str | None:
    """Intercept an action token Claude emitted and perform it.

    Returns a clean confirmation message to replace the raw reply, or None when
    the reply contains no action token (normal chat). ``DRAFT_EMAIL:`` tokens are
    only honored when ``allow_draft`` is True — a defensive second gate on top of
    stripping the draft protocol from the system prompt.
    """
    first_line, _, _ = reply.partition("\n")
    first_line = first_line.strip()

    if allow_draft and first_line.startswith("DRAFT_EMAIL:"):
        try:
            params = json.loads(first_line[len("DRAFT_EMAIL:") :])
        except json.JSONDecodeError:
            logger.warning("Malformed DRAFT_EMAIL token: %s", first_line)
            return None
        # Refuse to save a draft addressed to nobody / garbage — ask instead.
        to_email = (params.get("to_email") or "").strip()
        if not EMAIL_RE.match(to_email):
            logger.warning("DRAFT_EMAIL missing/invalid to_email: %r", to_email)
            return "Who should I address this email to? Please give me an email address."
        account_id = params.get("account_id")
        if not account_id:
            accounts = await gmail_service.list_accounts(db)
            if not accounts:
                return "I couldn't draft that — no email account is connected yet."
            account_id = accounts[0]["id"]
        try:
            await draft_service.generate_draft(
                account_id=account_id,
                to_email=to_email,
                subject=params.get("subject", ""),
                context=params.get("context", ""),
                db=db,
                thread_email_id=params.get("thread_email_id"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Draft generation from chat failed")
            return "I ran into a problem drafting that email."
        return "Draft saved to your Drafts panel."

    if first_line.startswith("CALENDAR_CREATE:"):
        try:
            params = json.loads(first_line[len("CALENDAR_CREATE:") :])
        except json.JSONDecodeError:
            logger.warning("Malformed CALENDAR_CREATE token: %s", first_line)
            return None
        account_id = params.get("account_id")
        if not account_id:
            accounts = await gmail_service.list_accounts(db)
            if not accounts:
                return "I couldn't create that event — no account is connected yet."
            account_id = accounts[0]["id"]
        title = params.get("title", "Untitled event")
        start = params.get("start", "")
        end = params.get("end", "")
        try:
            await calendar_service.create_event(
                account_id=account_id,
                title=title,
                start_time=start,
                end_time=end,
                db=db,
                description=params.get("description", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Calendar event creation from chat failed")
            return "I ran into a problem creating that event."
        return f"Done — {title} added to your calendar{_friendly_when(start)}."

    return None


def _friendly_when(start: str) -> str:
    """Render an ISO start time as ' for June 19 at 3:00 PM' (empty on parse failure)."""
    try:
        when = datetime.fromisoformat(start)
    except (ValueError, TypeError):
        return ""
    return f" for {when.strftime('%B %-d')} at {when.strftime('%-I:%M %p')}"


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


async def _persist_exchange(
    db: AsyncSession,
    user_message: str,
    reply: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total: int = 0,
) -> None:
    """Persist a user/assistant exchange, accumulate token usage, mirror to Obsidian."""
    await db.execute(
        text(
            "INSERT INTO chat_messages (role, content, tokens_used) "
            "VALUES ('user', :content, NULL)"
        ),
        {"content": user_message},
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
        await obsidian_service.append_exchange(user_message, reply)
    except Exception:  # noqa: BLE001 — never fail a chat over a note write
        logger.exception("Obsidian daily-note append failed")


@router.post("/message", response_model=ChatResponse)
async def send_message(payload: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Send a user message to Claude and persist the exchange + token usage."""
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")

    # "Give me the digest" short-circuits normal chat: build the brief and return
    # its voice-ready text so callers (voice/TTS) read it aloud.
    if _is_digest_request(payload.message):
        try:
            digest = await digest_service.build_digest(db)
            reply = digest["full_text"]
        except Exception:  # noqa: BLE001
            logger.exception("Digest request failed")
            reply = "I couldn't put together your brief right now."
        await _persist_exchange(db, payload.message, reply, total=0)
        return ChatResponse(
            response=reply, tokens=TokenUsage(input=0, output=0, total=0)
        )

    try:
        accounts = await gmail_service.list_accounts(db)
    except Exception:  # noqa: BLE001
        accounts = []

    # Only expose the draft action protocol when the user explicitly asked to
    # draft/write/send an email — keeps Claude from hallucinating drafts.
    draft_intent = is_draft_intent(payload.message)

    calendar_context = await _calendar_context(db)
    obsidian_context = await obsidian_service.get_obsidian_context(payload.message, db)
    email_context = await vector_service.get_email_context(payload.message, db)
    contact_context = await contact_service.get_contact_context(payload.message, db)
    tone = await settings_service.get_value(db, "response_tone")
    system = claude_service.build_system_prompt(
        calendar_context=calendar_context,
        obsidian_context=obsidian_context,
        email_context=email_context,
        contact_context=contact_context,
        accounts=accounts,
        tone=tone,
        allow_draft=draft_intent,
    )

    messages = await _recent_history(db)
    messages.append({"role": "user", "content": payload.message})

    try:
        reply, usage = await provider_service.call_chat(db, system=system, messages=messages)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat request to AI provider failed")
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}") from exc

    # If Claude emitted an action token (e.g. drafting an email), perform it and
    # replace the raw reply with a clean confirmation before persisting/returning.
    action_reply = await _maybe_handle_action(reply, db, allow_draft=draft_intent)
    if action_reply is not None:
        reply = action_reply

    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    total = input_tokens + output_tokens

    await _persist_exchange(
        db,
        payload.message,
        reply,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total=total,
    )

    return ChatResponse(
        response=reply,
        tokens=TokenUsage(input=input_tokens, output=output_tokens, total=total),
    )


@router.get("/messages", response_model=list[ChatMessageOut])
async def get_messages(
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return today's messages oldest-first to pre-load on page open.

    Only today's messages are returned — every morning the chat starts fresh.
    Previous days are written to Obsidian daily notes and remain accessible
    via RAG when the user asks about them.
    """
    result = await db.execute(
        text(
            "SELECT role, content, created_at "
            "FROM chat_messages "
            "WHERE DATE(created_at) = CURRENT_DATE "
            "ORDER BY id ASC "
            "LIMIT :limit"
        ),
        {"limit": limit},
    )
    return [
        ChatMessageOut(
            role=row["role"], content=row["content"], created_at=row["created_at"]
        )
        for row in result.mappings().all()
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
