"""Meridian's memory layer — direct PostgreSQL note storage.

This module replaces the old Obsidian vault integration. Every memory
(email/contact summaries, chat exchanges, sent mail) is written straight to the
``notes`` table and embedded immediately via the configured embedding model, so
it's searchable for RAG retrieval without any filesystem or background watcher.

Embedding happens synchronously inside :func:`write_note`. If embedding fails,
the note is still written with a NULL embedding (and ``is_vectorized = FALSE``)
and a warning is logged — a write must never fail because embedding failed.
"""

import logging
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


async def embed_text(text_value: str, db: AsyncSession | None = None) -> list[float] | None:
    """Embed a single string with the configured model. Returns None on failure."""
    from services.vector_service import embed_texts

    try:
        results = await embed_texts([text_value], db)
    except Exception:  # noqa: BLE001 — caller writes the note with a NULL embedding
        logger.exception("memory_service: embedding failed")
        return None
    return results[0] if results else None


async def _embed_literal(text_value: str, db: AsyncSession | None) -> str | None:
    """Embed text and render it as a pgvector literal, or None if unavailable.

    Validates the embedding dimension against the configured model so a stale or
    mismatched vector is never stored — a mismatch is treated as a soft failure.
    """
    from services import vector_service
    from services.vector_service import to_pgvector

    embedding = await embed_text(text_value, db)
    if embedding is None:
        return None
    try:
        expected_dim = (await vector_service.get_embedding_config(db))["dim"]
    except Exception:  # noqa: BLE001
        expected_dim = len(embedding)
    if len(embedding) != expected_dim:
        logger.warning(
            "memory_service: embedding dim mismatch (got %s, expected %s) — storing NULL",
            len(embedding),
            expected_dim,
        )
        return None
    return to_pgvector(embedding)


# ---------------------------------------------------------------------------
# Core write path
# ---------------------------------------------------------------------------


async def write_note(
    title: str,
    content: str,
    note_type: str,
    source_id: int | None,
    wikilinks: list[str],
    db: AsyncSession,
) -> int:
    """Write a note to the ``notes`` table and embed it immediately.

    If a note with the same title already exists, the new content is appended to
    it (separated by a horizontal rule) rather than creating a duplicate. Returns
    the note id.
    """
    existing = await db.execute(
        text("SELECT id, content FROM notes WHERE title = :title"),
        {"title": title},
    )
    row = existing.fetchone()

    if row:
        updated_content = (row.content or "") + "\n\n---\n\n" + content
        literal = await _embed_literal(updated_content, db)
        await db.execute(
            text(
                """
                UPDATE notes
                SET content = :content,
                    embedding = """
                + ("CAST(:embedding AS vector)" if literal else "NULL")
                + """,
                    is_vectorized = :vectorized,
                    wikilinks = :wikilinks,
                    note_type = :note_type,
                    source_id = COALESCE(:source_id, source_id),
                    last_modified = NOW(),
                    updated_at = NOW()
                WHERE id = :id
                """
            ),
            {
                "content": updated_content,
                **({"embedding": literal} if literal else {}),
                "vectorized": literal is not None,
                "wikilinks": wikilinks,
                "note_type": note_type,
                "source_id": source_id,
                "id": row.id,
            },
        )
        await db.commit()
        return row.id

    literal = await _embed_literal(content, db)
    result = await db.execute(
        text(
            """
            INSERT INTO notes
                (title, content, note_type, source_id, wikilinks, embedding,
                 is_vectorized, file_path, last_modified, updated_at)
            VALUES
                (:title, :content, :note_type, :source_id, :wikilinks, """
            + ("CAST(:embedding AS vector)" if literal else "NULL")
            + """,
                 :vectorized, :file_path, NOW(), NOW())
            RETURNING id
            """
        ),
        {
            "title": title,
            "content": content,
            "note_type": note_type,
            "source_id": source_id,
            "wikilinks": wikilinks,
            **({"embedding": literal} if literal else {}),
            "vectorized": literal is not None,
            # Synthetic path kept only to satisfy the file_path UNIQUE constraint.
            "file_path": f"pg://{note_type}/{title}",
        },
    )
    await db.commit()
    return result.scalar()


async def append_to_note(title: str, new_content: str, db: AsyncSession) -> None:
    """Append content to an existing note, creating it if it doesn't exist."""
    await write_note(
        title=title,
        content=new_content,
        note_type="general",
        source_id=None,
        wikilinks=[],
        db=db,
    )


# ---------------------------------------------------------------------------
# Typed note writers — one per memory source
# ---------------------------------------------------------------------------


async def write_daily_note(
    date_str: str, user_message: str, assistant_message: str, db: AsyncSession
) -> None:
    """Append a daily chat exchange to that day's note."""
    title = f"Daily/{date_str}"
    content = f"**You:** {user_message}\n\n**Meridian:** {assistant_message}"
    await write_note(
        title=title,
        content=content,
        note_type="daily",
        source_id=None,
        wikilinks=extract_wikilinks(f"{user_message} {assistant_message}"),
        db=db,
    )


async def write_email_note(
    thread_id: int,
    contact_name: str,
    subject: str,
    summary: str,
    participants: list[str],
    db: AsyncSession,
) -> None:
    """Write an email thread summary as a note (source_id = email_threads.id)."""
    title = f"Emails/{contact_name}/{subject}"[:200]
    content = (
        f"# {subject}\n\n"
        f"*Participants: {', '.join(participants)}*\n\n"
        f"## Summary\n\n{summary}\n"
    )
    wikilinks = [p.split("@")[0] for p in participants if "@" in p]
    await write_note(
        title=title,
        content=content,
        note_type="email",
        source_id=thread_id,
        wikilinks=wikilinks,
        db=db,
    )


async def write_contact_note(
    contact_id: int,
    display_name: str,
    email: str,
    topics: list[str],
    email_count: int,
    db: AsyncSession,
) -> None:
    """Write a contact profile as a note (source_id = contacts.id)."""
    title = f"Contacts/{display_name}"
    content = (
        f"# {display_name}\n\n"
        f"*Email: {email} · {email_count} emails exchanged*\n\n"
        f"## Topics\n\n{', '.join(topics)}\n"
    )
    await write_note(
        title=title,
        content=content,
        note_type="contact",
        source_id=contact_id,
        wikilinks=[],
        db=db,
    )


async def write_persistent_chat_note(
    chat_id: str,
    title: str,
    user_message: str,
    assistant_message: str,
    db: AsyncSession,
) -> None:
    """Write/append a persistent-chat exchange to its note."""
    note_title = f"Chats/{title}"
    content = f"**You:** {user_message}\n\n**Meridian:** {assistant_message}"
    await write_note(
        title=note_title,
        content=content,
        note_type="persistent_chat",
        source_id=None,
        wikilinks=[],
        db=db,
    )


async def write_sent_email_note(
    to_email: str, subject: str, body: str, sent_at: datetime, db: AsyncSession
) -> None:
    """Write a sent email to memory for a permanent record."""
    date_str = sent_at.strftime("%Y-%m-%d")
    title = f"Sent/{date_str}-{subject[:60]}"
    content = (
        f"# {subject}\n\n"
        f"*Sent: {sent_at.strftime('%B %d, %Y at %I:%M %p')} · To: {to_email}*\n\n"
        f"## Content\n\n{body}\n"
    )
    await write_note(
        title=title,
        content=content,
        note_type="sent",
        source_id=None,
        wikilinks=[to_email.split("@")[0]] if "@" in to_email else [],
        db=db,
    )


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


async def search_notes(
    query: str,
    note_types: list[str] | None,
    limit: int,
    db: AsyncSession,
) -> list[dict]:
    """Vector similarity search over notes, optionally filtered by note_type."""
    from services.vector_service import to_pgvector

    embedding = await embed_text(query, db)
    if embedding is None:
        return []

    params: dict = {"embedding": to_pgvector(embedding), "limit": limit}
    type_filter = ""
    if note_types:
        type_filter = "AND note_type = ANY(:types)"
        params["types"] = note_types

    result = await db.execute(
        text(
            f"""
            SELECT id, title, content, note_type, source_id,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM notes
            WHERE embedding IS NOT NULL
            {type_filter}
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        params,
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def get_email_context(query: str, db: AsyncSession, limit: int = 5) -> str:
    """Return email + contact note context for chat RAG."""
    results = await search_notes(query, ["email", "contact"], limit, db)
    if not results:
        return ""
    context = "Relevant information from your knowledge base:\n\n"
    for r in results:
        snippet = (r["content"] or "")[:600]
        context += f"### {r['title']}\n{snippet}\n\n"
    return context.rstrip()


async def get_general_context(query: str, db: AsyncSession, limit: int = 3) -> str:
    """Return general/daily/persistent-chat note context for chat RAG."""
    results = await search_notes(query, ["daily", "persistent_chat", "general"], limit, db)
    if not results:
        return ""
    context = "Relevant notes from your memory:\n\n"
    for r in results:
        context += f"### {r['title']}\n{(r['content'] or '')[:400]}\n\n"
    return context.rstrip()


# ---------------------------------------------------------------------------
# Bulk export — replaces the old Obsidian background exporters
# ---------------------------------------------------------------------------


async def export_threads_to_memory(account_id: int) -> None:
    """Write all email threads for an account to the notes table (background task).

    Generates a short AI summary per thread, derives the primary contact, and
    writes one note per thread. Progress is tracked in user_settings so the
    existing Connections UI can poll it.
    """
    from db.database import AsyncSessionLocal
    from services import settings_service

    progress_key = f"obsidian_export_progress_{account_id}"

    async with AsyncSessionLocal() as db:
        accounts_result = await db.execute(text("SELECT email FROM gmail_accounts"))
        all_user_emails = [row.email for row in accounts_result.fetchall()]
        user_usernames = [e.split("@")[0].lower() for e in all_user_emails]

        threads_result = await db.execute(
            text(
                """
                SELECT id, thread_id, subject, participants, message_count, last_message_at
                FROM email_threads
                WHERE account_id = :account_id
                ORDER BY last_message_at DESC
                """
            ),
            {"account_id": account_id},
        )
        thread_rows = threads_result.fetchall()
        total = len(thread_rows)
        logger.info("Exporting %s threads to memory for account %s", total, account_id)

        await settings_service.set_value(
            db, progress_key, _progress(0, total)
        )

        processed = 0
        for thread in thread_rows:
            try:
                participants = thread.participants or []
                contact_name = _primary_contact(participants, all_user_emails, user_usernames)

                messages_result = await db.execute(
                    text(
                        """
                        SELECT from_address, body_text
                        FROM emails
                        WHERE thread_id = :thread_id AND account_id = :account_id
                        ORDER BY received_at ASC
                        LIMIT 5
                        """
                    ),
                    {"thread_id": thread.thread_id, "account_id": account_id},
                )
                messages = [dict(r._mapping) for r in messages_result.fetchall()]
                messages_text = "\n\n".join(
                    f"From: {m.get('from_address', '')}\n{(m.get('body_text') or '')[:300]}"
                    for m in messages
                )
                summary = await _summarize_thread(thread.subject or "(no subject)", messages_text)

                await write_email_note(
                    thread_id=thread.id,
                    contact_name=contact_name,
                    subject=thread.subject or "(no subject)",
                    summary=summary,
                    participants=participants,
                    db=db,
                )
                processed += 1
                if processed % 50 == 0:
                    await settings_service.set_value(db, progress_key, _progress(processed, total))
            except Exception:  # noqa: BLE001 — skip one bad thread, keep going
                logger.warning("Failed to write thread %s to memory", thread.thread_id)
                continue

        await settings_service.set_value(db, progress_key, _progress(total, total, done=True))
        logger.info("Memory export complete for account %s: %s threads", account_id, total)


async def export_contacts_to_memory(account_id: int | None = None) -> None:
    """Write all contacts to the notes table (background task)."""
    from db.database import AsyncSessionLocal
    from services import settings_service

    progress_key = "obsidian_contacts_export_progress"

    async with AsyncSessionLocal() as db:
        contacts_result = await db.execute(
            text(
                """
                SELECT id, email_address, display_name, email_count, last_contacted
                FROM contacts
                ORDER BY email_count DESC
                """
            )
        )
        contacts = contacts_result.fetchall()
        total = len(contacts)
        logger.info("Exporting %s contacts to memory", total)

        await settings_service.set_value(db, progress_key, _progress(0, total))

        processed = 0
        for contact in contacts:
            try:
                name = contact.display_name or contact.email_address.split("@")[0]
                topics = await _contact_topics(contact.email_address, db)
                await write_contact_note(
                    contact_id=contact.id,
                    display_name=name,
                    email=contact.email_address,
                    topics=topics,
                    email_count=contact.email_count or 0,
                    db=db,
                )
                processed += 1
                if processed % 100 == 0:
                    await settings_service.set_value(db, progress_key, _progress(processed, total))
            except Exception:  # noqa: BLE001
                logger.warning("Failed to write contact %s to memory", contact.email_address)
                continue

        await settings_service.set_value(db, progress_key, _progress(total, total, done=True))
        logger.info("Contacts memory export complete: %s contacts", total)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(value: str) -> list[str]:
    """Extract ``[[wikilink]]`` patterns from text."""
    return list(dict.fromkeys(_WIKILINK.findall(value)))


def _progress(processed: int, total: int, done: bool = False) -> str:
    import json

    return json.dumps({"processed": processed, "total": total, "done": done})


def _primary_contact(
    participants: list[str], user_emails: list[str], user_usernames: list[str]
) -> str:
    """Pick the first participant who isn't the user; fall back to 'Self'."""
    for participant in participants:
        p_lower = participant.lower()
        if any(ue.lower() in p_lower for ue in user_emails):
            continue
        if any(uu in p_lower.split("@")[0] for uu in user_usernames):
            continue
        name = participant
        if "<" in name:
            name = name[: name.index("<")].strip() or name
        if "@" in name:
            name = name.split("@")[0]
        return re.sub(r"[^\w\s-]", "", name).strip() or "Unknown"
    return "Self"


async def _summarize_thread(subject: str, messages_text: str) -> str:
    """2-3 sentence AI summary of an email thread (best-effort)."""
    from config import get_settings

    settings = get_settings()
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize this email thread in 2-3 sentences. Be specific about "
                    "what was discussed and any decisions made. No emojis.\n\n"
                    f"Subject: {subject}\n\n{messages_text[:1500]}"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception:  # noqa: BLE001
        logger.warning("Thread summary generation failed for: %s", subject)
        return f"Email thread about {subject}."


async def _contact_topics(email_address: str, db: AsyncSession) -> list[str]:
    """Derive topic keywords from a contact's email subjects (best-effort)."""
    try:
        result = await db.execute(
            text(
                """
                SELECT DISTINCT subject FROM emails
                WHERE from_address = :email OR :email = ANY(to_addresses)
                ORDER BY subject LIMIT 10
                """
            ),
            {"email": email_address},
        )
        subjects = [r[0] for r in result.fetchall() if r[0]]
    except Exception:  # noqa: BLE001
        return []
    return subjects[:8]


# ---------------------------------------------------------------------------
# Future feature stub
# ---------------------------------------------------------------------------


async def export_to_obsidian(vault_path: str, db: AsyncSession) -> dict:
    """NOT YET IMPLEMENTED — future one-time export of all notes to an Obsidian vault.

    Will write each note as a .md file with wikilinks preserved. Notes currently
    live in PostgreSQL and will be browsable via the planned /graph page.
    """
    raise NotImplementedError(
        "Obsidian export is planned but not yet implemented. "
        "Notes are stored in PostgreSQL and accessible via the /graph page (coming soon)."
    )
