"""Obsidian vault integration — Meridian's long-term memory layer.

This module writes conversation exchanges into daily notes and extracts
wikilinks so the vault graph grows over time. The vault location always comes
from the ``OBSIDIAN_VAULT_PATH`` environment variable — never hardcoded. When
it is unset, every operation degrades to a no-op so chat still works.

Vault ingestion and RAG retrieval build on this module in later steps.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import anthropic
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

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)

# Cache: hash(text) → extracted entity list so identical text isn't re-sent to Claude.
_wikilink_cache: dict[int, list[str]] = {}

_ENTITY_EXTRACTION_PROMPT = """\
Extract named entities from this text that would make meaningful Obsidian wikilinks.
Only include: proper nouns, project names, organization names, product names, place names, and people's names.
Do not include: common words, verbs, adjectives, pronouns, or single generic nouns.
Return a JSON array of strings only, no other text.
Text: {text}"""


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


async def extract_wikilinks(text: str) -> list[str]:
    """Use Claude Haiku to extract meaningful named-entity wikilinks from text.

    Results are cached by text hash so repeated calls within a vault watch cycle
    don't re-hit the API. Returns an empty list on any API failure so daily-note
    writing still succeeds.
    """
    cache_key = hash(text)
    if cache_key in _wikilink_cache:
        return _wikilink_cache[cache_key]

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": _ENTITY_EXTRACTION_PROMPT.format(text=text),
            }],
        )
        raw = message.content[0].text.strip()
        parsed = json.loads(raw)
        links = [str(item) for item in parsed if isinstance(item, str)][:8]
    except Exception:
        logger.exception("Claude Haiku wikilink extraction failed — returning no links")
        links = []

    _wikilink_cache[cache_key] = links
    return links


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


async def append_exchange(
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
    links = await extract_wikilinks(assistant_message)

    def _write() -> bool:
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
            content = _merge_related(content, links)
            note_path.write_text(content, encoding="utf-8")
            return True
        except OSError:
            logger.exception("Failed to write Obsidian daily note")
            return False

    return await asyncio.to_thread(_write)


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


async def scan_vault_on_startup() -> None:
    """Ingest all existing vault notes that aren't yet in the database.

    Runs once at startup before the watcher loop begins so notes that existed
    before Meridian was first launched (e.g. Welcome.md) are immediately
    available for RAG retrieval without waiting for a file-system event.
    """
    vault = vault_path()
    if vault is None:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT file_path FROM obsidian_notes"))
        existing = {row[0] for row in result.fetchall()}

    ingested = 0
    for md_file in vault.rglob("*.md"):
        if str(md_file) not in existing:
            async with AsyncSessionLocal() as db:
                await ingest_note(md_file, db)
            ingested += 1

    logger.info("Startup vault scan complete — ingested %s new note(s)", ingested)


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


_OBSIDIAN_EMBED_MODEL = "voyage-3-lite"
_OBSIDIAN_EMBED_DIM = 512


async def _embed_texts_for_obsidian(texts: list[str]) -> list[list[float]]:
    """Embed texts with the model hardcoded — no shared constant — to guarantee 512 dims."""
    import voyageai
    client = voyageai.Client(api_key=settings.voyage_api_key)
    result = await asyncio.to_thread(client.embed, texts, _OBSIDIAN_EMBED_MODEL)
    return result.embeddings


async def vectorize_pending_notes(db: AsyncSession) -> int:
    """Embed up to one batch of not-yet-vectorized notes via VoyageAI."""
    if not settings.voyage_api_key:
        return 0
    # to_pgvector is a pure formatting helper — no embedding logic shared.
    from services.vector_service import to_pgvector

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
        embeddings = await _embed_texts_for_obsidian(texts)
    except Exception:  # noqa: BLE001
        logger.exception("VoyageAI embedding failed for Obsidian notes")
        return 0

    embedded = 0
    for note, embedding in zip(notes, embeddings):
        if len(embedding) != _OBSIDIAN_EMBED_DIM:
            logger.error(
                "Note %s embedding dimension mismatch — got %s, expected %s from %s — skipped.",
                note["id"],
                len(embedding),
                _OBSIDIAN_EMBED_DIM,
                _OBSIDIAN_EMBED_MODEL,
            )
            continue
        await db.execute(
            text(
                "UPDATE obsidian_notes SET embedding = CAST(:embedding AS vector), "
                "is_vectorized = TRUE WHERE id = :id"
            ),
            {"embedding": to_pgvector(embedding), "id": note["id"]},
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
    from services.vector_service import to_pgvector

    try:
        query_embedding = (await _embed_texts_for_obsidian([query]))[0]
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
        {"embedding": to_pgvector(query_embedding), "limit": limit},
    )
    notes = result.mappings().all()
    if not notes:
        return ""

    context = "Relevant notes from your Obsidian vault:\n\n"
    for note in notes:
        context += f"### {note['title']}\n{(note['content'] or '')[:500]}\n\n"
    return context.rstrip()
