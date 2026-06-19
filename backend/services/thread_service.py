"""Email threading: roll messages up into conversations for thread-aware RAG.

Gmail already groups messages by ``thread_id``; this service materializes that
grouping into the ``email_threads`` table — one row per conversation with its
participants, message count, and a single embedding built from the whole thread.
Chat RAG then retrieves entire conversations instead of fragmented messages.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import AsyncSessionLocal
from services import vector_service

logger = logging.getLogger(__name__)
settings = get_settings()

# Cap the concatenated thread body fed to the embedder so a long conversation
# doesn't blow past the model's context or dominate the vector.
_SUMMARY_BODY_CHARS = 2000


def _thread_summary(subject: str, participants: list[str], bodies: list[str]) -> str:
    """Build the text we embed for a thread: subject, participants, then bodies."""
    joined = "\n\n".join(b for b in bodies if b).strip()
    return (
        f"Thread: {subject or '(no subject)'}\n"
        f"Participants: {', '.join(participants)}\n\n"
        f"{joined[:_SUMMARY_BODY_CHARS]}"
    )


async def build_threads(account_id: int, db: AsyncSession) -> dict:
    """Group an account's emails into threads, upsert, and embed each thread.

    Returns ``{built, total}`` over the distinct threads for the account.
    """
    result = await db.execute(
        text(
            """
            SELECT id, thread_id, from_address, to_addresses, subject,
                   body_text, received_at
            FROM emails
            WHERE account_id = :account_id AND thread_id IS NOT NULL
            ORDER BY thread_id, received_at ASC
            """
        ),
        {"account_id": account_id},
    )
    rows = list(result.mappings().all())

    # Group rows by Gmail thread_id, preserving chronological order.
    threads: dict[str, list[dict]] = {}
    for row in rows:
        threads.setdefault(row["thread_id"], []).append(dict(row))

    can_embed = bool(settings.voyage_api_key)
    built = 0
    for thread_id, messages in threads.items():
        # The subject of the first message is the canonical thread subject.
        subject = messages[0]["subject"] or ""
        last_message_at = messages[-1]["received_at"]

        participants: list[str] = []
        for msg in messages:
            if msg["from_address"]:
                participants.append(msg["from_address"])
            for addr in msg["to_addresses"] or []:
                participants.append(addr)
        # Dedupe while keeping first-seen order.
        participants = list(dict.fromkeys(participants))

        embedding_literal = None
        if can_embed:
            summary = _thread_summary(
                subject, participants, [m["body_text"] or "" for m in messages]
            )
            try:
                embedding = (await vector_service.embed_texts([summary]))[0]
            except Exception:  # noqa: BLE001 — leave is_vectorized FALSE, retry later
                logger.exception("Failed to embed thread %s", thread_id)
            else:
                if len(embedding) == vector_service.EMBED_DIM:
                    embedding_literal = vector_service.to_pgvector(embedding)

        upsert = await db.execute(
            text(
                """
                INSERT INTO email_threads
                    (account_id, thread_id, subject, participants, message_count,
                     last_message_at, embedding, is_vectorized)
                VALUES
                    (:account_id, :thread_id, :subject, :participants, :message_count,
                     :last_message_at,
                     CASE WHEN :embedding IS NULL THEN NULL ELSE CAST(:embedding AS vector) END,
                     :is_vectorized)
                ON CONFLICT (account_id, thread_id) DO UPDATE SET
                    subject = EXCLUDED.subject,
                    participants = EXCLUDED.participants,
                    message_count = EXCLUDED.message_count,
                    last_message_at = EXCLUDED.last_message_at,
                    embedding = EXCLUDED.embedding,
                    is_vectorized = EXCLUDED.is_vectorized
                RETURNING id
                """
            ),
            {
                "account_id": account_id,
                "thread_id": thread_id,
                "subject": subject,
                "participants": participants,
                "message_count": len(messages),
                "last_message_at": last_message_at,
                "embedding": embedding_literal,
                "is_vectorized": embedding_literal is not None,
            },
        )
        thread_db_id = upsert.scalar_one()

        # Point every message in this thread at its parent thread row.
        await db.execute(
            text(
                "UPDATE emails SET thread_db_id = :thread_db_id "
                "WHERE account_id = :account_id AND thread_id = :thread_id"
            ),
            {
                "thread_db_id": thread_db_id,
                "account_id": account_id,
                "thread_id": thread_id,
            },
        )
        await db.commit()
        built += 1

    logger.info("Built %s threads for account %s", built, len(threads))
    return {"built": built, "total": len(threads)}


async def run_build_threads_background(account_id: int) -> None:
    """Entry point for FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await build_threads(account_id, db)
        except Exception:  # noqa: BLE001
            logger.exception("Background thread build failed for account %s", account_id)


async def build_progress(account_id: int, db: AsyncSession) -> dict:
    """Return ``{processed, total}`` — built threads vs distinct thread_ids."""
    result = await db.execute(
        text(
            """
            SELECT
                (SELECT COUNT(DISTINCT thread_id) FROM emails
                 WHERE account_id = :account_id AND thread_id IS NOT NULL) AS total,
                (SELECT COUNT(*) FROM email_threads
                 WHERE account_id = :account_id) AS processed
            """
        ),
        {"account_id": account_id},
    )
    row = result.mappings().first()
    return {
        "processed": int(row["processed"] or 0) if row else 0,
        "total": int(row["total"] or 0) if row else 0,
    }
