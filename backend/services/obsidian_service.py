"""Obsidian vault integration — Meridian's long-term memory layer.

This module writes conversation exchanges into daily notes and extracts
wikilinks so the vault graph grows over time. The vault location always comes
from the ``OBSIDIAN_VAULT_PATH`` environment variable — never hardcoded. When
it is unset, every operation degrades to a no-op so chat still works.

Vault ingestion and RAG retrieval build on this module in later steps.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

# How often the background tasks run.
WATCH_INTERVAL_SECONDS = 30
VECTORIZE_INTERVAL_SECONDS = 300
NOTE_VECTORIZE_BATCH = 128

# Section headings of a daily note, in order. Conversations grow at the top;
# Related (wikilinks) sits at the bottom and is merged on each exchange.
SECTIONS = (
    "## Conversations with Meridian",
    "## Tasks & Reminders",
    "## Ideas & Notes",
    "## Related",
)

# Capitalized words that are almost never entities worth linking.
_WIKILINK_STOPWORDS = {
    "you", "your", "yours", "meridian", "the", "a", "an", "i", "it", "we",
    "they", "he", "she", "this", "that", "these", "those", "here", "there",
    "today", "tomorrow", "yesterday", "ok", "okay", "yes", "no", "sure",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "am", "pm", "let", "let's",
    "if", "so", "and", "but", "or", "to", "of", "in", "on", "at", "for",
}

_CAPITALIZED_PHRASE = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b")
_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def vault_path() -> Path | None:
    """Resolve the configured vault root, or None when OBSIDIAN_VAULT_PATH is unset."""
    if not settings.obsidian_vault_path:
        return None
    return Path(settings.obsidian_vault_path).expanduser()


def _format_date(when: datetime) -> str:
    return f"{when.strftime('%B')} {when.day}, {when.year}"


def _format_time(when: datetime) -> str:
    hour = when.hour % 12 or 12
    meridiem = "AM" if when.hour < 12 else "PM"
    return f"{hour}:{when.minute:02d} {meridiem}"


def extract_wikilinks(text: str) -> list[str]:
    """Heuristically pull proper-noun phrases to link in the Related section.

    Favors multi-word capitalized phrases and longer single TitleCase words;
    filters common sentence-initial words. Imperfect by design — over many
    conversations the graph fills in.
    """
    links: list[str] = []
    for phrase in _CAPITALIZED_PHRASE.findall(text):
        words = phrase.split()
        # Trim common opener/closer words ("Your MIT" → "MIT").
        while words and words[0].lower() in _WIKILINK_STOPWORDS:
            words.pop(0)
        while words and words[-1].lower() in _WIKILINK_STOPWORDS:
            words.pop()
        if not words:
            continue
        cleaned = " ".join(words)
        # Drop lone 1–2 char fragments; keep acronyms like MIT and any phrase.
        if len(words) == 1 and (len(cleaned) < 3 or cleaned.lower() in _WIKILINK_STOPWORDS):
            continue
        if cleaned not in links:
            links.append(cleaned)
    return links[:8]


def _new_note(when: datetime) -> str:
    return f"# {_format_date(when)}\n\n" + "\n\n".join(SECTIONS) + "\n"


def _insert_into_section(content: str, heading: str, addition: str) -> str:
    """Insert ``addition`` at the end of ``heading``'s section (before the next ##)."""
    lines = content.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        # Heading absent (e.g. a hand-edited note) — append it at the end.
        return content.rstrip("\n") + f"\n\n{heading}\n{addition}"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    if not addition.endswith("\n"):
        addition += "\n"
    return "".join(lines[:end] + [addition] + lines[end:])


def _merge_related(content: str, new_links: list[str]) -> str:
    existing = set(_WIKILINK.findall(content))
    additions = [link for link in new_links if link not in existing]
    if not additions:
        return content
    block = "".join(f"- [[{link}]]\n" for link in additions)
    return _insert_into_section(content, "## Related", block)


def append_exchange(
    user_message: str, assistant_message: str, when: datetime | None = None
) -> bool:
    """Append one conversation exchange to today's daily note.

    Creates ``{vault}/Daily/`` and the note if needed, preserves existing
    content, and merges any new wikilinks into Related. Returns False (no-op)
    when no vault is configured.
    """
    vault = vault_path()
    if vault is None:
        return False

    when = when or datetime.now()
    try:
        daily_dir = vault / "Daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        note_path = daily_dir / f"{when.strftime('%Y-%m-%d')}.md"

        content = (
            note_path.read_text(encoding="utf-8") if note_path.exists() else _new_note(when)
        )
        block = (
            f"\n### {_format_time(when)}\n"
            f"**You:** {user_message.strip()}\n\n"
            f"**Meridian:** {assistant_message.strip()}\n"
        )
        content = _insert_into_section(content, SECTIONS[0], block)
        content = _merge_related(content, extract_wikilinks(assistant_message))

        note_path.write_text(content, encoding="utf-8")
        return True
    except OSError:
        logger.exception("Failed to write Obsidian daily note")
        return False


# ---------------------------------------------------------------------------
# Vault ingestion — pull .md files into PostgreSQL for RAG retrieval
# ---------------------------------------------------------------------------


async def ingest_note(md_file: Path, db: AsyncSession) -> None:
    """Upsert one .md file into ``obsidian_notes``, flagged for (re)embedding."""
    try:
        content = md_file.read_text(encoding="utf-8", errors="ignore")
        mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
    except OSError:
        logger.exception("Could not read vault note %s", md_file)
        return

    heading = _HEADING.search(content)
    title = heading.group(1).strip() if heading else md_file.stem
    # Preserve order, drop duplicates.
    wikilinks = list(dict.fromkeys(_WIKILINK.findall(content)))

    await db.execute(
        text(
            """
            INSERT INTO obsidian_notes
                (file_path, title, content, wikilinks, last_modified, is_vectorized)
            VALUES (:file_path, :title, :content, :wikilinks, :last_modified, FALSE)
            ON CONFLICT (file_path) DO UPDATE SET
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                wikilinks = EXCLUDED.wikilinks,
                last_modified = EXCLUDED.last_modified,
                is_vectorized = FALSE
            """
        ),
        {
            "file_path": str(md_file),
            "title": title,
            "content": content,
            "wikilinks": wikilinks,
            "last_modified": mtime,
        },
    )
    await db.commit()


async def watch_vault(poll_seconds: int = WATCH_INTERVAL_SECONDS) -> None:
    """Poll the vault for new/modified .md files and ingest them (runs forever)."""
    vault = vault_path()
    if vault is None:
        logger.info("OBSIDIAN_VAULT_PATH not set — vault watcher disabled")
        return

    logger.info("Watching Obsidian vault at %s", vault)
    seen: dict[str, float] = {}
    while True:
        try:
            for md_file in vault.rglob("*.md"):
                try:
                    mtime = md_file.stat().st_mtime
                except OSError:
                    continue
                key = str(md_file)
                if seen.get(key) != mtime:
                    seen[key] = mtime
                    async with AsyncSessionLocal() as db:
                        await ingest_note(md_file, db)
        except Exception:  # noqa: BLE001 — keep the loop alive across failures
            logger.exception("Vault watch iteration failed")
        await asyncio.sleep(poll_seconds)


async def vectorize_pending_notes(db: AsyncSession) -> int:
    """Embed up to one batch of not-yet-vectorized notes via VoyageAI."""
    if not settings.voyage_api_key:
        return 0
    # Imported here to keep this module importable without the embeddings stack.
    from services import vector_service

    result = await db.execute(
        text(
            "SELECT id, title, content FROM obsidian_notes "
            "WHERE is_vectorized = FALSE ORDER BY id LIMIT :limit"
        ),
        {"limit": NOTE_VECTORIZE_BATCH},
    )
    notes = [dict(row) for row in result.mappings().all()]
    if not notes:
        return 0

    texts = [f"{note['title'] or ''}\n\n{(note['content'] or '')[:4000]}" for note in notes]
    try:
        embeddings = await vector_service.embed_texts(texts)
    except Exception:  # noqa: BLE001
        logger.exception("VoyageAI embedding failed for Obsidian notes")
        return 0

    embedded = 0
    for note, embedding in zip(notes, embeddings):
        if len(embedding) != vector_service.EMBED_DIM:
            logger.error("Note %s embedding dimension mismatch — skipped", note["id"])
            continue
        await db.execute(
            text(
                "UPDATE obsidian_notes SET embedding = CAST(:embedding AS vector), "
                "is_vectorized = TRUE WHERE id = :id"
            ),
            {"embedding": vector_service.to_pgvector(embedding), "id": note["id"]},
        )
        embedded += 1
    await db.commit()
    return embedded


async def vectorize_notes_loop(poll_seconds: int = VECTORIZE_INTERVAL_SECONDS) -> None:
    """Periodically embed freshly ingested notes (runs forever)."""
    if vault_path() is None:
        return
    while True:
        try:
            async with AsyncSessionLocal() as db:
                embedded = await vectorize_pending_notes(db)
            if embedded:
                logger.info("Embedded %s Obsidian note(s)", embedded)
        except Exception:  # noqa: BLE001
            logger.exception("Obsidian note vectorization iteration failed")
        await asyncio.sleep(poll_seconds)


# ---------------------------------------------------------------------------
# RAG retrieval — surface relevant vault notes for a chat query
# ---------------------------------------------------------------------------


async def get_obsidian_context(query: str, db: AsyncSession, limit: int = 3) -> str:
    """Return the most relevant vault notes for ``query`` as system-prompt context.

    Embeds the query and runs a pgvector cosine-similarity search over the
    ingested notes. Returns an empty string when there's no key, no embedded
    notes, or on any failure — chat should never break over missing context.
    """
    if not settings.voyage_api_key:
        return ""
    from services import vector_service

    try:
        query_embedding = (await vector_service.embed_texts([query]))[0]
    except Exception:  # noqa: BLE001
        logger.exception("Failed to embed chat query for Obsidian retrieval")
        return ""

    result = await db.execute(
        text(
            """
            SELECT title, content,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM obsidian_notes
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {"embedding": vector_service.to_pgvector(query_embedding), "limit": limit},
    )
    notes = result.mappings().all()
    if not notes:
        return ""

    context = "Relevant notes from your Obsidian vault:\n\n"
    for note in notes:
        context += f"### {note['title']}\n{(note['content'] or '')[:500]}\n\n"
    return context.rstrip()
