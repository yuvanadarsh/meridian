"""Email draft generation in the user's writing voice.

Builds a style profile from the user's own past emails (RAG over sent history),
then asks Claude to draft a new email that matches that voice. Drafts are stored
in the ``drafts`` table for review in the Drafts panel before anything is sent.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services import provider_service

logger = logging.getLogger(__name__)

_DRAFT_PROMPT = """\
You are drafting an email on behalf of the user. Match their writing style exactly based on the examples below.

{style_profile}

Draft an email with these details:
To: {to_email}
Subject: {subject}
Context/intent: {context}
{thread_context}

Rules:
- Match the user's tone, vocabulary, and sentence length from the examples.
- Do not add signatures unless the examples show them.
- Do not be overly formal unless the examples are formal.
- Write only the email body, no subject line, no preamble, no quotes around it."""


async def get_style_profile(account_id: int, db: AsyncSession) -> str:
    """Pull up to 10 of the user's own past emails to establish writing style.

    Filters to emails whose ``from_address`` matches the account address, so the
    examples are genuinely the user's own writing rather than received mail.
    Returns an empty string when no suitable examples exist.
    """
    result = await db.execute(
        text(
            """
            SELECT subject, body_text FROM emails
            WHERE account_id = :account_id
              AND from_address LIKE '%' || (
                  SELECT email FROM gmail_accounts WHERE id = :account_id
              ) || '%'
              AND triage_status IN ('keep', 'archive')
              AND body_text IS NOT NULL
              AND length(body_text) > 50
            ORDER BY received_at DESC
            LIMIT 10
            """
        ),
        {"account_id": account_id},
    )
    sent = result.mappings().all()
    if not sent:
        return ""

    examples = "\n\n---\n\n".join(
        f"Subject: {row['subject']}\n{(row['body_text'] or '')[:300]}" for row in sent
    )
    return f"Writing style examples from the user's past emails:\n\n{examples}"


async def _thread_context(thread_email_id: int | None, db: AsyncSession) -> str:
    """Build reply context from the email being replied to, if any."""
    if thread_email_id is None:
        return ""
    result = await db.execute(
        text(
            "SELECT from_address, subject, body_text FROM emails WHERE id = :id"
        ),
        {"id": thread_email_id},
    )
    row = result.mappings().first()
    if row is None:
        return ""
    return (
        "You are replying to this email:\n"
        f"From: {row['from_address']}\n"
        f"Subject: {row['subject']}\n"
        f"{(row['body_text'] or '')[:1000]}"
    )


async def generate_draft(
    account_id: int,
    to_email: str,
    subject: str,
    context: str,
    db: AsyncSession,
    thread_email_id: int | None = None,
) -> dict:
    """Generate a draft email in the user's voice and persist it as pending.

    Returns the stored draft row as a dict.
    """
    style_profile = await get_style_profile(account_id, db)
    thread_context = await _thread_context(thread_email_id, db)

    prompt = _DRAFT_PROMPT.format(
        style_profile=style_profile or "(No past emails available to learn the style from.)",
        to_email=to_email,
        subject=subject,
        context=context,
        thread_context=thread_context,
    )

    body, _ = await provider_service.call_draft(
        db, system="", messages=[{"role": "user", "content": prompt}], max_tokens=1024
    )

    result = await db.execute(
        text(
            """
            INSERT INTO drafts (account_id, to_email, subject, body, thread_email_id, status)
            VALUES (:account_id, :to_email, :subject, :body, :thread_email_id, 'pending')
            RETURNING id, account_id, to_email, subject, body, thread_email_id, status,
                      created_at, updated_at
            """
        ),
        {
            "account_id": account_id,
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "thread_email_id": thread_email_id,
        },
    )
    row = result.mappings().first()
    await db.commit()
    return dict(row)
