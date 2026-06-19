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
    logger.info("Thread build starting for account %s", account_id)

    try:
        # Diagnostic: confirm emails exist for this account before proceeding.
        count_result = await db.execute(
            text("SELECT count(*) FROM emails WHERE account_id = :account_id"),
            {"account_id": account_id},
        )
        email_count = count_result.scalar() or 0
        logger.info("Account %s has %s emails in DB", account_id, email_count)

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

        logger.info("Found %s distinct threads for account %s", len(threads), account_id)
        if not threads:
            logger.warning(
                "No emails with thread_id found for account %s — "
                "check that account_id matches emails.account_id and that sweep completed",
                account_id,
            )
            return {"built": 0, "total": 0}

        embed_config = await vector_service.get_embedding_config(db)
        can_embed = embed_config["provider"] != "voyage" or bool(settings.voyage_api_key)
        expected_dim = embed_config["dim"]
        logger.info(
            "Embedding config for account %s: provider=%s model=%s dim=%s can_embed=%s",
            account_id, embed_config["provider"], embed_config["model"], expected_dim, can_embed,
        )

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
                    embedding = (await vector_service.embed_texts([summary], db))[0]
                except Exception:  # noqa: BLE001 — leave is_vectorized FALSE, retry later
                    logger.exception("Failed to embed thread %s", thread_id)
                else:
                    if len(embedding) == expected_dim:
                        embedding_literal = vector_service.to_pgvector(embedding)

            # Step 1: upsert thread row without embedding to avoid asyncpg type ambiguity.
            upsert = await db.execute(
                text(
                    """
                    INSERT INTO email_threads
                        (account_id, thread_id, subject, participants, message_count,
                         last_message_at, is_vectorized)
                    VALUES
                        (:account_id, :thread_id, :subject, :participants, :message_count,
                         :last_message_at, :is_vectorized)
                    ON CONFLICT (account_id, thread_id) DO UPDATE SET
                        subject = EXCLUDED.subject,
                        participants = EXCLUDED.participants,
                        message_count = EXCLUDED.message_count,
                        last_message_at = EXCLUDED.last_message_at,
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
                    "is_vectorized": embedding_literal is not None,
                },
            )
            thread_db_id = upsert.scalar_one()

            # Step 2: interpolate the vector string directly — asyncpg cannot parse
            # the :param::vector syntax, so we embed the sanitized literal in the SQL.
            if embedding_literal is not None:
                safe_vec = embedding_literal.replace("'", "")
                await db.execute(
                    text(f"UPDATE email_threads SET embedding = '{safe_vec}'::vector WHERE id = :id"),
                    {"id": thread_db_id},
                )

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

        logger.info("Thread build complete for account %s: %s / %s threads built", account_id, built, len(threads))
        return {"built": built, "total": len(threads)}

    except Exception:
        logger.error("Thread build failed for account %s", account_id, exc_info=True)
        raise


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
