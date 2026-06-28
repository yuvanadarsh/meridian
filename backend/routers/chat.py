"""Chat routes: Claude conversation with calendar context and token tracking."""

import json
import logging
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

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
    draft_service,
    gmail_service,
    obsidian_service,
    provider_service,
    settings_service,
    usage_service,
    vector_service,
)

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/chat", tags=["chat"])

HISTORY_LIMIT = 10

# Phrases that indicate the user wants a full Gmail thread fetch (tier 2).
_DEEP_PHRASES = (
    "tell me more",
    "go deeper",
    "full details",
    "complete thread",
    "show me everything",
    "read the full",
)

async def _get_context_tiered(
    message: str, db: AsyncSession, tier: int = 1
) -> tuple[str, str]:
    """Return (context_text, source_label) using a tiered retrieval strategy.

    Tier 1 searches Obsidian Email/Contact notes first, falls back to raw email
    DB if nothing found. Tier 2 fetches the full thread from Gmail API, writes
    an enriched note to Obsidian, and returns the complete content.
    """
    # Always try Obsidian email/contact notes first
    obsidian_email_ctx = await obsidian_service.get_obsidian_email_context(message, db, limit=5)
    logger.info(
        "Obsidian email context returned %d chars for query: %s",
        len(obsidian_email_ctx),
        message[:50],
    )

    if tier == 1:
        if obsidian_email_ctx:
            return obsidian_email_ctx, "obsidian"
        email_ctx = await vector_service.get_email_context(message, db, limit=5)
        if email_ctx:
            return email_ctx, "email_db"
        return "", "none"

    # Tier 2: find the most relevant thread and fetch it from Gmail
    try:
        query_embedding = (await vector_service.embed_texts([message]))[0]
        from services.vector_service import to_pgvector

        thread_result = await db.execute(
            text(
                """
                SELECT thread_id, account_id, subject, participants, message_count, last_message_at
                FROM email_threads
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT 1
                """
            ),
            {"embedding": to_pgvector(query_embedding)},
        )
        thread_row = thread_result.mappings().first()
        if thread_row is None:
            return obsidian_email_ctx or "", "obsidian"

        thread_id = thread_row["thread_id"]
        account_id = thread_row["account_id"]

        # Fetch full thread from Gmail API
        full_messages = await gmail_service.get_full_thread_from_gmail(thread_id, account_id, db)
        if full_messages:
            # Enrich the Obsidian note with full content
            accounts_result = await db.execute(
                text("SELECT email FROM gmail_accounts WHERE id = :id"),
                {"id": account_id},
            )
            user_emails = [row.email for row in accounts_result.fetchall()]
            try:
                await obsidian_service.write_thread_to_vault(
                    thread_id=thread_id,
                    subject=thread_row["subject"] or "(no subject)",
                    participants=thread_row["participants"] or [],
                    message_count=thread_row["message_count"] or len(full_messages),
                    last_message_at=thread_row["last_message_at"] or datetime.utcnow(),
                    messages=full_messages,
                    user_emails=user_emails,
                    db=db,
                )
                logger.info(
                    "Tier 2 retrieval: fetched full thread %s from Gmail, wrote to Obsidian",
                    thread_id,
                )
            except Exception:
                logger.exception("Tier 2 Obsidian write failed for thread %s", thread_id)

            # Build context from full messages — inject directly; don't wait for Obsidian vectorization
            ctx = "Full email thread (fetched directly from Gmail):\n\n"
            for msg in full_messages:
                received = msg.get("received_at")
                date_str = received.strftime("%B %d, %Y") if isinstance(received, datetime) else ""
                ctx += f"From: {msg.get('from_address', '')}\n"
                ctx += f"Date: {date_str}\n"
                ctx += f"{(msg.get('body_text') or '')[:800]}\n\n---\n\n"
            return ctx.rstrip(), "gmail_api"
    except Exception:
        logger.exception("Tier 2 retrieval failed")

    return obsidian_email_ctx or "", "obsidian"


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

# A calendar event awaiting the user's confirmation after a conflict warning.
# This is a local, single-user app, so a module-level slot is enough — there's
# no per-session state to track.
_pending_event: dict | None = None

# Affirmative replies that confirm a pending (conflicting) calendar event.
_AFFIRMATIVE_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok|okay|confirm|go ahead|schedule anyway|do it|please do)\b",
    re.IGNORECASE,
)


def is_draft_intent(message: str) -> bool:
    """True only when the user explicitly asks to draft/write/send an email.

    Used to decide whether to expose the ``DRAFT_EMAIL:`` action protocol to
    Claude at all. Keeping this strict prevents accidental drafts on questions
    like "what did Max email me about?".
    """
    msg_lower = message.lower()
    return any(phrase in msg_lower for phrase in DRAFT_TRIGGER_PHRASES)


# Words/phrases that mean "send this to me" — must be resolved to the user's
# own email address rather than running a normal contact search.
_SELF_REFERENTIAL = {
    "myself", "me", "my email", "to me", "yourself",
    "my own email", "my gmail", "my account", "i", "my inbox",
}


def _is_self_referential(message: str) -> bool:
    """True when the draft recipient is the user themselves."""
    msg_lower = message.lower().strip()
    return any(ref in msg_lower for ref in _SELF_REFERENTIAL)


async def _calendar_context(db: AsyncSession) -> str:
    """Build a combined calendar block for all connected accounts.

    Fetches today's events and upcoming events (next 7 days) across every
    linked account. Returns empty string when there are no accounts or events
    so nothing leaks into the system prompt. Times are converted to the user's
    configured timezone before formatting.
    """
    try:
        accounts = await gmail_service.list_accounts(db)
    except Exception:
        return ""
    if not accounts:
        return ""

    # Resolve user timezone; fall back to calendar service default.
    try:
        tz_value = await settings_service.get_value(db, "timezone")
        user_tz = ZoneInfo(tz_value or calendar_service.DEFAULT_TIMEZONE)
    except Exception:
        user_tz = ZoneInfo(calendar_service.DEFAULT_TIMEZONE)

    def _to_local(dt: datetime) -> datetime:
        """Convert a naive-UTC datetime to the user's local timezone."""
        return dt.replace(tzinfo=timezone.utc).astimezone(user_tz)

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
                s = _to_local(start).strftime("%I:%M %p").lstrip("0")
                e = _to_local(end).strftime("%I:%M %p").lstrip("0")
                today_lines.append(f"- {s} – {e}: {title}")
            elif start:
                today_lines.append(f"- {_to_local(start).strftime('%I:%M %p').lstrip('0')}: {title}")
            else:
                today_lines.append(f"- {title}")

        for event in upcoming_events:
            start = event["start_time"]
            title = event["title"] or "(untitled)"
            # Exclude events already shown in today's block.
            local_start = _to_local(start) if start else None
            if local_start and local_start.date() > today:
                upcoming_lines.append(f"- {local_start.strftime('%B %-d')}: {title}")

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
        return await _handle_calendar_create(params, db)

    if first_line.startswith("CALENDAR_CONFIRM:"):
        # Claude can confirm a pending (conflicting) event; the affirmative-reply
        # path in the endpoint covers a plain "yes" too.
        return await _confirm_pending_event(db)

    return None


async def _resolve_account_id(params: dict, db: AsyncSession) -> int | None:
    """Use the token's account_id, or fall back to the first connected account."""
    account_id = params.get("account_id")
    if account_id:
        return account_id
    accounts = await gmail_service.list_accounts(db)
    return accounts[0]["id"] if accounts else None


async def _handle_calendar_create(params: dict, db: AsyncSession) -> str:
    """Create a calendar event, warning first if it overlaps an existing one."""
    global _pending_event

    account_id = await _resolve_account_id(params, db)
    if account_id is None:
        return "I couldn't create that event — no account is connected yet."

    title = params.get("title", "Untitled event")
    start = params.get("start", "")
    end = params.get("end", "")

    # Check for overlapping events before creating anything.
    conflicts = []
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        conflicts = await calendar_service.check_conflicts(account_id, start_dt, end_dt, db)
    except (ValueError, TypeError):
        # Unparseable times — skip the conflict check and let create_event try.
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Conflict check failed; proceeding to create")

    if conflicts:
        _pending_event = {
            "account_id": account_id,
            "title": title,
            "start": start,
            "end": end,
            "description": params.get("description", ""),
        }
        desc = ", ".join(f"{_conflict_title(c)} at {_conflict_when(c)}" for c in conflicts)
        return (
            f"You already have {desc} at that time. "
            "Should I schedule anyway? Reply 'yes' to confirm."
        )

    return await _create_calendar_event(
        {
            "account_id": account_id,
            "title": title,
            "start": start,
            "end": end,
            "description": params.get("description", ""),
        },
        db,
    )


async def _create_calendar_event(event: dict, db: AsyncSession) -> str:
    """Insert the event and return a friendly confirmation message."""
    global _pending_event
    try:
        try:
            tz_val = await settings_service.get_value(db, "timezone")
            user_tz = tz_val or calendar_service.DEFAULT_TIMEZONE
        except Exception:
            user_tz = calendar_service.DEFAULT_TIMEZONE
        await calendar_service.create_event(
            account_id=event["account_id"],
            title=event["title"],
            start_time=event["start"],
            end_time=event["end"],
            db=db,
            description=event.get("description", ""),
            user_tz=user_tz,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Calendar event creation from chat failed")
        return "I ran into a problem creating that event."
    _pending_event = None
    return f"Done — {event['title']} added to your calendar{_friendly_when(event['start'])}."


async def _confirm_pending_event(db: AsyncSession) -> str:
    """Create the event held after a conflict warning, if any."""
    if not _pending_event:
        return "There's no event waiting to be confirmed."
    return await _create_calendar_event(_pending_event, db)


def _conflict_title(row) -> str:
    return getattr(row, "title", None) or "an event"


def _conflict_when(row) -> str:
    """Render a stored (UTC-naive) conflict start time in the user's local time."""
    start = getattr(row, "start_time", None)
    if not isinstance(start, datetime):
        return "that time"
    local = start.replace(tzinfo=timezone.utc).astimezone(
        ZoneInfo(calendar_service.DEFAULT_TIMEZONE)
    )
    return local.strftime("%-I:%M %p")


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
    # DEPRECATED: token_usage is legacy. Usage is tracked in usage_log via usage_service.
    # This write is kept for backward compatibility only and will be removed in a future cleanup.
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
    global _pending_event

    if not settings.anthropic_api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")

    # If an event is awaiting confirmation after a conflict warning, resolve it
    # from this message directly instead of round-tripping through Claude.
    if _pending_event is not None:
        if _AFFIRMATIVE_RE.match(payload.message):
            reply = await _confirm_pending_event(db)
            await _persist_exchange(db, payload.message, reply, total=0)
            return ChatResponse(response=reply, tokens=TokenUsage(input=0, output=0, total=0))
        if re.match(r"^\s*(no|nope|cancel|don'?t|never\s?mind)\b", payload.message, re.IGNORECASE):
            _pending_event = None
            reply = "Okay, I won't schedule it."
            await _persist_exchange(db, payload.message, reply, total=0)
            return ChatResponse(response=reply, tokens=TokenUsage(input=0, output=0, total=0))

    try:
        accounts = await gmail_service.list_accounts(db)
    except Exception:  # noqa: BLE001
        accounts = []

    # Only expose the draft action protocol when the user explicitly asked to
    # draft/write/send an email — keeps Claude from hallucinating drafts.
    draft_intent = is_draft_intent(payload.message)

    calendar_context = await _calendar_context(db)
    obsidian_context = await obsidian_service.get_obsidian_context(payload.message, db)

    # Tiered email/contact retrieval: Obsidian notes first, DB fallback, Gmail API on demand.
    tier = 2 if any(p in payload.message.lower() for p in _DEEP_PHRASES) else 1
    email_context, context_source = await _get_context_tiered(payload.message, db, tier=tier)
    contact_context = await contact_service.get_contact_context(payload.message, db)

    # Short-circuit contact lookup when the user is drafting to themselves so
    # the most-recently-mentioned contact address is never substituted.
    self_email: str | None = None
    if draft_intent and _is_self_referential(payload.message):
        result = await db.execute(text("SELECT email FROM gmail_accounts LIMIT 1"))
        row = result.fetchone()
        if row:
            self_email = row.email
            contact_context += (
                f"\nDraft target: {self_email} (the user's own email address). "
                "Use this address as to_email — do not substitute any other address."
            )

    tone = await settings_service.get_value(db, "response_tone")
    try:
        tz_val = await settings_service.get_value(db, "timezone")
        user_tz = tz_val or "America/New_York"
    except Exception:
        user_tz = "America/New_York"

    system = claude_service.build_system_prompt(
        calendar_context=calendar_context,
        obsidian_context=obsidian_context,
        email_context=email_context,
        contact_context=contact_context,
        accounts=accounts,
        tone=tone,
        allow_draft=draft_intent,
        self_email=self_email,
        user_tz=user_tz,
    )
    if context_source != "none":
        system += f"\nContext source: {context_source}"

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
    """Return today's accumulated token usage.

    Reads from usage_log (the multi-provider source of truth) so this endpoint
    and GET /usage/today return consistent data across all providers.
    """
    data = await usage_service.get_usage_today(db)
    return TokensToday(
        total=data["total_tokens_today"],
        input=data.get("by_provider", {}).get("anthropic", {}).get("types", {}).get("input_tokens", {}).get("units", 0),
        output=data.get("by_provider", {}).get("anthropic", {}).get("types", {}).get("output_tokens", {}).get("units", 0),
    )
