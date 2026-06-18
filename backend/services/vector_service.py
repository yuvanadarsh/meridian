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
