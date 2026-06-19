"""VoyageAI embeddings for emails (and Obsidian notes), stored in pgvector.

Only ``keep`` and ``archive`` emails are embedded — ``trash`` is never
vectorized (it's deleted on approval) and ``unreadable`` is skipped. The
embedding model and dimension are fixed to match the ``vector(512)`` columns.
"""

import asyncio
import logging

import httpx
import voyageai
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

# Project default (CLAUDE.md): voyage-3-lite at 512 dims. The active model is
# configurable via the ``embedding_model`` user setting; the revectorize flow
# migrates the vector() columns when the dimension changes.
EMBED_MODEL = "voyage-3-lite"
EMBED_DIM = 512
EMBED_BATCH_SIZE = 128

# Supported embedding models and their dimensions/providers. Used to validate a
# revectorize request and to size the vector() columns.
EMBEDDING_MODELS = {
    "voyage-3-lite": {"dim": 512, "provider": "voyage"},
    "voyage-large-2": {"dim": 1024, "provider": "voyage"},
    "text-embedding-3-small": {"dim": 1536, "provider": "openai"},
    "nomic-embed-text": {"dim": 768, "provider": "ollama"},
}

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


async def get_embedding_config(db: AsyncSession | None) -> dict:
    """Resolve the active embedding model from settings, with the project default.

    Returns ``{"model", "dim", "provider"}``. Falls back to voyage-3-lite when no
    setting is stored or the stored model is unknown.
    """
    model = EMBED_MODEL
    if db is not None:
        result = await db.execute(
            text("SELECT value FROM user_settings WHERE key = 'embedding_model'")
        )
        row = result.mappings().first()
        if row and row["value"] in EMBEDDING_MODELS:
            model = row["value"]
    config = EMBEDDING_MODELS.get(model, EMBEDDING_MODELS[EMBED_MODEL])
    return {"model": model, **config}


async def embed_texts(texts: list[str], db: AsyncSession | None = None) -> list[list[float]]:
    """Embed texts with the configured model, routing to the right provider.

    When ``db`` is provided the model comes from the ``embedding_model`` setting;
    otherwise the project default (voyage-3-lite) is used. Voyage uses its SDK;
    OpenAI and Ollama go over their HTTP embeddings endpoints.
    """
    config = await get_embedding_config(db)
    provider = config["provider"]
    model = config["model"]

    if provider == "voyage":
        client = get_client()
        result = await asyncio.to_thread(client.embed, texts, model=model)
        return result.embeddings
    if provider == "openai":
        return await _embed_openai(texts, model, db)
    if provider == "ollama":
        return await _embed_ollama(texts, model, db)
    raise ValueError(f"Unsupported embedding provider: {provider}")


async def _provider_creds(db: AsyncSession | None, provider: str) -> tuple[str | None, str | None]:
    """Return ``(api_key, base_url)`` for an embedding provider from ai_providers."""
    if db is None:
        return None, None
    # Imported lazily to avoid a circular import at module load.
    from services import provider_service

    result = await db.execute(
        text("SELECT api_key, base_url FROM ai_providers WHERE provider = :p"),
        {"p": provider},
    )
    row = result.mappings().first()
    if not row:
        return None, None
    api_key = None
    if row["api_key"]:
        from services import crypto

        try:
            api_key = crypto.decrypt(row["api_key"])
        except Exception:  # noqa: BLE001
            logger.error("Failed to decrypt %s key for embeddings", provider)
    base_url = row["base_url"] or provider_service.OPENAI_COMPATIBLE_BASE_URLS.get(provider)
    return api_key, base_url


async def _embed_openai(texts: list[str], model: str, db: AsyncSession | None) -> list[list[float]]:
    api_key, base_url = await _provider_creds(db, "openai")
    base_url = base_url or "https://api.openai.com/v1"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers=headers,
            json={"model": model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
    return [item["embedding"] for item in data["data"]]


async def _embed_ollama(texts: list[str], model: str, db: AsyncSession | None) -> list[list[float]]:
    _, base_url = await _provider_creds(db, "ollama")
    base_url = base_url or "http://localhost:11434"
    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(timeout=120) as http:
        for chunk in texts:
            response = await http.post(
                f"{base_url.rstrip('/')}/api/embeddings",
                json={"model": model, "prompt": chunk},
            )
            response.raise_for_status()
            embeddings.append(response.json()["embedding"])
    return embeddings


async def vectorize_account(account_id: int, db: AsyncSession) -> dict:
    """Embed every not-yet-vectorized keep/archive email for an account."""
    config = await get_embedding_config(db)
    expected_dim = config["dim"]
    if config["provider"] == "voyage" and not settings.voyage_api_key:
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
            embeddings = await embed_texts(texts, db)
        except Exception:  # noqa: BLE001 — stop this run, leave the rest for a retry
            logger.exception("Embedding failed for account %s", account_id)
            break

        for email, embedding in zip(batch, embeddings):
            if len(embedding) != expected_dim:
                logger.error(
                    "Embedding dim %s != expected %s for model %s — email %s skipped. "
                    "Model and vector(%s) column must agree.",
                    len(embedding),
                    expected_dim,
                    config["model"],
                    email["id"],
                    expected_dim,
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
    # Skip retrieval only when the default Voyage model is active but unconfigured.
    config = await get_embedding_config(db)
    if config["provider"] == "voyage" and not settings.voyage_api_key:
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
        query_embedding = (await embed_texts([query], db))[0]
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
        query_embedding = (await embed_texts([query], db))[0]
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


# ---------------------------------------------------------------------------
# Revectorize — switch the embedding model and re-embed the whole corpus
# ---------------------------------------------------------------------------

# Tables whose vector() columns are resized + reset when the dimension changes.
_EMBEDDED_TABLES = ("emails", "email_threads", "obsidian_notes", "contacts")

# Simple in-process status for the revectorize background task.
_revectorize_state = {"status": "idle", "model": EMBED_MODEL}


async def revectorize(model: str, db: AsyncSession) -> dict:
    """Switch the embedding model and queue a full re-embed.

    Validates the model, resizes every vector() column when the dimension
    changes (ALTER TABLE), clears existing embeddings, and persists the new
    model/dim settings. Returns ``{"queued": True}`` — the actual re-embedding
    runs in a background task started by the caller.
    """
    if model not in EMBEDDING_MODELS:
        raise ValueError(f"Unknown embedding model: {model}")

    new_dim = EMBEDDING_MODELS[model]["dim"]
    current = await db.execute(
        text("SELECT value FROM user_settings WHERE key = 'embedding_dim'")
    )
    row = current.mappings().first()
    current_dim = int(row["value"]) if row else EMBED_DIM

    # Resize the vector columns only when the dimension actually changes.
    if new_dim != current_dim:
        for table in _EMBEDDED_TABLES:
            try:
                await db.execute(
                    text(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector({new_dim})")
                )
            except Exception:  # noqa: BLE001 — table may not exist yet; keep going
                logger.warning("Could not alter embedding column on %s", table)
                await db.rollback()

    # Clear all embeddings so the background task re-embeds from scratch.
    for table in _EMBEDDED_TABLES:
        flag = ", is_vectorized = FALSE" if table != "contacts" else ""
        try:
            await db.execute(text(f"UPDATE {table} SET embedding = NULL{flag}"))
        except Exception:  # noqa: BLE001
            await db.rollback()

    await db.execute(
        text(
            """
            INSERT INTO user_settings (key, value, updated_at) VALUES
                ('embedding_model', :model, NOW()),
                ('embedding_dim', :dim, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """
        ),
        {"model": model, "dim": str(new_dim)},
    )
    await db.commit()
    return {"queued": True}


async def run_revectorize_background(model: str) -> None:
    """Re-embed emails, threads, contacts, and notes with the new model."""
    from services import contact_service, thread_service

    _revectorize_state.update(status="running", model=model)
    try:
        async with AsyncSessionLocal() as db:
            accounts = await db.execute(text("SELECT id FROM gmail_accounts"))
            account_ids = [r[0] for r in accounts.all()]

        for account_id in account_ids:
            async with AsyncSessionLocal() as db:
                await vectorize_account(account_id, db)
                await thread_service.build_threads(account_id, db)
                await contact_service.build_contact_graph(account_id, db)

        # Drain pending Obsidian notes in batches until none remain.
        from services import obsidian_service

        while True:
            async with AsyncSessionLocal() as db:
                embedded = await obsidian_service.vectorize_pending_notes(db)
            if not embedded:
                break

        _revectorize_state["status"] = "complete"
    except Exception:  # noqa: BLE001
        logger.exception("Revectorize background task failed")
        _revectorize_state["status"] = "error"


async def revectorize_progress(db: AsyncSession) -> dict:
    """Return ``{total, done, status}`` across all embedded corpora."""
    total = 0
    done = 0
    # emails (keep/archive) + threads + notes are the meaningful corpora.
    queries = (
        ("SELECT COUNT(*) FILTER (WHERE is_vectorized) d, COUNT(*) t FROM emails "
         "WHERE triage_status IN ('keep','archive')"),
        "SELECT COUNT(*) FILTER (WHERE is_vectorized) d, COUNT(*) t FROM email_threads",
        "SELECT COUNT(*) FILTER (WHERE is_vectorized) d, COUNT(*) t FROM obsidian_notes",
    )
    for query in queries:
        try:
            row = (await db.execute(text(query))).mappings().first()
        except Exception:  # noqa: BLE001 — table may not exist
            await db.rollback()
            continue
        if row:
            done += int(row["d"] or 0)
            total += int(row["t"] or 0)
    return {"total": total, "done": done, "status": _revectorize_state["status"]}
