"""VoyageAI embeddings for emails (and Obsidian notes), stored in pgvector.

Only ``keep`` and ``archive`` emails are embedded — ``trash`` is never
vectorized (it's deleted on approval) and ``unreadable`` is skipped. The
embedding model and dimension are fixed to match the ``vector(512)`` columns.
"""

import asyncio
import logging

import voyageai
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

# Project standard (CLAUDE.md): voyage-3-lite at 512 dims, matching the
# vector(512) columns. If a future model changes the dimension, update both
# this constant and the schema together.
EMBED_MODEL = "voyage-3-lite"
EMBED_DIM = 512
EMBED_BATCH_SIZE = 128

_client: voyageai.Client | None = None


def get_client() -> voyageai.Client:
    """Return a lazily-created VoyageAI client."""
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def to_pgvector(embedding: list[float]) -> str:
    """Render an embedding as pgvector's text literal: ``[v1,v2,...]``."""
    return "[" + ",".join(repr(float(value)) for value in embedding) + "]"


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts via VoyageAI, keeping the blocking SDK call off the loop."""
    client = get_client()
    result = await asyncio.to_thread(client.embed, texts, model=EMBED_MODEL)
    return result.embeddings


async def vectorize_account(account_id: int, db: AsyncSession) -> dict:
    """Embed every not-yet-vectorized keep/archive email for an account."""
    if not settings.voyage_api_key:
        logger.warning("VOYAGE_API_KEY not configured — skipping vectorization")
        return {"vectorized": 0, "total": 0}

    result = await db.execute(
        text(
            """
            SELECT id, subject, from_address, body_text
            FROM emails
            WHERE account_id = :account_id
              AND triage_status IN ('keep', 'archive')
              AND is_vectorized = FALSE
            ORDER BY id
            """
        ),
        {"account_id": account_id},
    )
    pending = [dict(row) for row in result.mappings().all()]

    vectorized = 0
    for batch in _chunks(pending, EMBED_BATCH_SIZE):
        texts = [
            f"Subject: {email['subject'] or ''}\n"
            f"From: {email['from_address'] or ''}\n\n"
            f"{(email['body_text'] or '')[:2000]}"
            for email in batch
        ]
        try:
            embeddings = await embed_texts(texts)
        except Exception:  # noqa: BLE001 — stop this run, leave the rest for a retry
            logger.exception("VoyageAI embedding failed for account %s", account_id)
            break

        for email, embedding in zip(batch, embeddings):
            if len(embedding) != EMBED_DIM:
                logger.error(
                    "Embedding dim %s != expected %s for model %s — email %s skipped. "
                    "Model and vector(%s) column must agree.",
                    len(embedding),
                    EMBED_DIM,
                    EMBED_MODEL,
                    email["id"],
                    EMBED_DIM,
                )
                continue
            await db.execute(
                text(
                    "UPDATE emails SET embedding = CAST(:embedding AS vector), "
                    "is_vectorized = TRUE WHERE id = :id"
                ),
                {"embedding": to_pgvector(embedding), "id": email["id"]},
            )
            vectorized += 1
        await db.commit()

    logger.info("Vectorized %s/%s emails for account %s", vectorized, len(pending), account_id)
    return {"vectorized": vectorized, "total": len(pending)}


async def run_vectorize_background(account_id: int) -> None:
    """Entry point for FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await vectorize_account(account_id, db)
        except Exception:  # noqa: BLE001
            logger.exception("Background vectorization failed for account %s", account_id)


# ---------------------------------------------------------------------------
# RAG retrieval — surface relevant emails for a chat query
# ---------------------------------------------------------------------------


async def get_email_context(query: str, db: AsyncSession, limit: int = 5) -> str:
    """Return relevant email *conversations* for ``query`` as prompt context.

    Thread-aware: retrieves whole conversations from ``email_threads`` (built via
    ``thread_service``) so Claude sees full back-and-forth context instead of
    isolated messages. Falls back to message-level retrieval only when no threads
    have been built yet. Returns an empty string on any failure — chat should
    never break over missing context.
    """
    if not settings.voyage_api_key:
        return ""

    # Only fall back to message-level search if the account hasn't built threads.
    thread_count = await db.execute(text("SELECT COUNT(*) FROM email_threads"))
    if (thread_count.scalar() or 0) > 0:
        return await _thread_email_context(query, db, limit=limit)
    return await _message_level_email_context(query, db, limit=max(limit, 10))


async def hybrid_email_search(query: str, db: AsyncSession, limit: int = 5) -> list:
    """Rank email threads by Reciprocal Rank Fusion of vector + full-text search.

    Combines pgvector cosine similarity with Postgres full-text (``search_vector``)
    ranking. RRF (``1 / (k + rank)``, k=60) fuses the two rankings so a thread that
    scores well on either signal surfaces — far more robust than vector-only when
    the query shares exact terms (names, subjects) with the email. Returns SQLAlchemy
    rows with ``thread_id, subject, participants, message_count, last_message_at``.
    """
    try:
        query_embedding = (await embed_texts([query]))[0]
    except Exception:  # noqa: BLE001
        logger.exception("Failed to embed chat query for thread retrieval")
        return []

    result = await db.execute(
        text(
            """
            WITH vector_results AS (
                SELECT thread_id, subject, participants, message_count, last_message_at,
                       ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:embedding AS vector)) AS vector_rank
                FROM email_threads
                WHERE embedding IS NOT NULL
                LIMIT 20
            ),
            text_results AS (
                SELECT thread_id, subject, participants, message_count, last_message_at,
                       ROW_NUMBER() OVER (ORDER BY ts_rank(search_vector, query) DESC) AS text_rank
                FROM email_threads,
                     plainto_tsquery('english', :query_text) query
                WHERE search_vector @@ query
                LIMIT 20
            ),
            combined AS (
                SELECT
                    COALESCE(v.thread_id, t.thread_id) AS thread_id,
                    COALESCE(v.subject, t.subject) AS subject,
                    COALESCE(v.participants, t.participants) AS participants,
                    COALESCE(v.message_count, t.message_count) AS message_count,
                    COALESCE(v.last_message_at, t.last_message_at) AS last_message_at,
                    (1.0 / (60 + COALESCE(v.vector_rank, 1000))) +
                    (1.0 / (60 + COALESCE(t.text_rank, 1000))) AS rrf_score
                FROM vector_results v
                FULL OUTER JOIN text_results t USING (thread_id)
            )
            SELECT * FROM combined ORDER BY rrf_score DESC LIMIT :limit
            """
        ),
        {
            "embedding": to_pgvector(query_embedding),
            "query_text": query,
            "limit": limit,
        },
    )
    return result.fetchall()


async def _thread_email_context(query: str, db: AsyncSession, limit: int = 5) -> str:
    """Retrieve the most relevant email threads and their recent messages."""
    threads = await hybrid_email_search(query, db, limit=limit)
    if not threads:
        return ""

    context = "Relevant email conversations:\n\n"
    for thread in threads:
        messages = await db.execute(
            text(
                """
                SELECT from_address, body_text, received_at
                FROM emails
                WHERE thread_id = :thread_id
                ORDER BY received_at ASC
                LIMIT 3
                """
            ),
            {"thread_id": thread.thread_id},
        )
        msgs = messages.fetchall()

        context += f"Thread: {thread.subject}\n"
        context += f"Participants: {', '.join(thread.participants or [])}\n"
        context += f"Messages: {thread.message_count}\n"
        for msg in msgs:
            when = msg.received_at.strftime("%b %d") if msg.received_at else ""
            context += f"\n[{when}] {msg.from_address}:\n"
            context += f"{(msg.body_text or '')[:300]}\n"
        context += "\n---\n\n"

    return context.rstrip()


async def _message_level_email_context(query: str, db: AsyncSession, limit: int = 10) -> str:
    """Legacy per-message retrieval — used before threads are built.

    Embeds the query, runs a pgvector cosine search, and falls back to an ILIKE
    keyword search when too few matches come back.
    """
    try:
        query_embedding = (await embed_texts([query]))[0]
    except Exception:  # noqa: BLE001
        logger.exception("Failed to embed chat query for email retrieval")
        return ""

    result = await db.execute(
        text(
            """
            SELECT from_address, subject, body_text, received_at
            FROM emails
            WHERE is_vectorized = TRUE
              AND triage_status IN ('keep', 'archive')
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {"embedding": to_pgvector(query_embedding), "limit": limit},
    )
    emails = list(result.mappings().all())

    # Keyword fallback when vector search finds too few matches
    if len(emails) < 3:
        seen_subjects = {e["subject"] for e in emails}
        keywords = query.split()[:3]
        for kw in keywords:
            kw_result = await db.execute(
                text(
                    """
                    SELECT from_address, subject, body_text, received_at
                    FROM emails
                    WHERE is_vectorized = TRUE
                      AND triage_status IN ('keep', 'archive')
                      AND (subject ILIKE :kw OR body_text ILIKE :kw)
                    LIMIT 5
                    """
                ),
                {"kw": f"%{kw}%"},
            )
            for row in kw_result.mappings().all():
                if row["subject"] not in seen_subjects:
                    emails.append(row)
                    seen_subjects.add(row["subject"])

    if not emails:
        return ""

    context = "Relevant emails from your inbox:\n\n"
    for email in emails:
        context += f"From: {email['from_address']}\n"
        context += f"Subject: {email['subject']}\n"
        context += f"Date: {email['received_at']}\n"
        context += f"Content: {(email['body_text'] or '')[:500]}\n\n"
    return context.rstrip()


async def vectorize_progress(account_id: int, db: AsyncSession) -> dict:
    """Return ``{vectorized, total}`` over an account's keep/archive emails."""
    result = await db.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_vectorized) AS vectorized,
                COUNT(*) AS total
            FROM emails
            WHERE account_id = :account_id AND triage_status IN ('keep', 'archive')
            """
        ),
        {"account_id": account_id},
    )
    row = result.mappings().first()
    return {
        "vectorized": int(row["vectorized"] or 0) if row else 0,
        "total": int(row["total"] or 0) if row else 0,
    }
