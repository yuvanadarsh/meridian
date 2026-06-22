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
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import aiofiles

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
        # Strip markdown code fences Haiku sometimes adds around JSON output.
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if not raw or raw == "[]":
            return []
        parsed = json.loads(raw)
        links = [str(item) for item in parsed if isinstance(item, str) and len(item) > 2][:8]
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


async def append_review_summaries(
    summaries: list[dict], when: datetime | None = None
) -> bool:
    """Append afternoon-review email summaries to today's daily note.

    Each item is ``{"subject", "from", "summary"}``. They're written as bullets
    under "## Ideas & Notes" so the day's reviewed mail lands in the knowledge
    layer. Returns False (no-op) when no vault is configured or there's nothing
    to write.
    """
    vault = vault_path()
    if vault is None or not summaries:
        return False

    when = when or datetime.now()

    def _write() -> bool:
        try:
            daily_dir = vault / "Daily"
            daily_dir.mkdir(parents=True, exist_ok=True)
            note_path = daily_dir / f"{when.strftime('%Y-%m-%d')}.md"
            content = (
                note_path.read_text(encoding="utf-8") if note_path.exists() else _new_note(when)
            )
            block = "\n#### Afternoon review\n"
            for item in summaries:
                subject = (item.get("subject") or "(no subject)").strip()
                sender = (item.get("from") or "").strip()
                summary = (item.get("summary") or "").strip()
                block += f"- **{subject}** — {sender}: {summary}\n"
            content = _insert_into_section(content, "## Ideas & Notes", block)
            note_path.write_text(content, encoding="utf-8")
            return True
        except OSError:
            logger.exception("Failed to write afternoon review summaries to daily note")
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


async def cleanup_vault_root_stubs() -> None:
    """Delete stray ``.md`` files in the vault root left by older export bugs.

    Early versions wrote contact and thread notes directly to the vault root
    instead of the ``Contacts/`` and ``Emails/`` subfolders. This removes those
    leftovers on startup, keeping only ``Welcome.md``. Subdirectories are never
    touched.
    """
    vault = vault_path()
    if vault is None:
        return

    KEEP_FILES = {"Welcome.md"}

    def _cleanup() -> int:
        removed = 0
        for item in os.listdir(vault):
            item_path = vault / item
            if item_path.is_file() and item.endswith(".md") and item not in KEEP_FILES:
                try:
                    item_path.unlink()
                    logger.info("Removed vault root stub: %s", item)
                    removed += 1
                except OSError:
                    logger.warning("Could not remove vault root stub: %s", item)
        return removed

    await asyncio.to_thread(_cleanup)


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


async def vectorize_pending_notes(db: AsyncSession) -> int:
    """Embed up to one batch of not-yet-vectorized notes via the configured model."""
    from services import vector_service
    from services.vector_service import to_pgvector

    config = await vector_service.get_embedding_config(db)
    if config["provider"] == "voyage" and not settings.voyage_api_key:
        return 0
    expected_dim = config["dim"]

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
        embeddings = await vector_service.embed_texts(texts, db)
    except Exception:  # noqa: BLE001
        logger.exception("Embedding failed for Obsidian notes")
        return 0

    embedded = 0
    for note, embedding in zip(notes, embeddings):
        if len(embedding) != expected_dim:
            logger.error(
                "Note %s embedding dimension mismatch — got %s, expected %s from %s — skipped.",
                note["id"],
                len(embedding),
                expected_dim,
                config["model"],
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
    from services import vector_service
    from services.vector_service import to_pgvector

    config = await vector_service.get_embedding_config(db)
    if config["provider"] == "voyage" and not settings.voyage_api_key:
        return ""

    try:
        query_embedding = (await vector_service.embed_texts([query], db))[0]
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


async def get_obsidian_email_context(query: str, db: AsyncSession, limit: int = 5) -> str:
    """Search only Email and Contact notes in the vault for RAG retrieval.

    Filters to notes under ``{vault}/Emails/`` or ``{vault}/Contacts/`` so the
    result is richer and more specific than the general ``get_obsidian_context``.
    """
    from services import vector_service
    from services.vector_service import to_pgvector

    config = await vector_service.get_embedding_config(db)
    if config["provider"] == "voyage" and not settings.voyage_api_key:
        return ""

    vault = vault_path()
    if vault is None:
        return ""

    try:
        query_embedding = (await vector_service.embed_texts([query], db))[0]
    except Exception:
        logger.exception("Failed to embed query for Obsidian email context")
        return ""

    email_prefix = str(vault / "Emails") + "%"
    contact_prefix = str(vault / "Contacts") + "%"

    result = await db.execute(
        text(
            """
            SELECT title, content, file_path,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM obsidian_notes
            WHERE embedding IS NOT NULL
              AND (file_path LIKE :email_prefix OR file_path LIKE :contact_prefix)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        ),
        {
            "embedding": to_pgvector(query_embedding),
            "email_prefix": email_prefix,
            "contact_prefix": contact_prefix,
            "limit": limit,
        },
    )
    notes = result.mappings().all()
    if not notes:
        return ""

    context = "Relevant information from your knowledge base:\n\n"
    for note in notes:
        context += f"### {note['title']}\n{(note['content'] or '')[:600]}\n\n"
    return context.rstrip()


# ---------------------------------------------------------------------------
# Email thread vault writer — unified memory layer
# ---------------------------------------------------------------------------


async def generate_thread_summary(subject: str, messages_text: str) -> str:
    """2-3 sentence AI summary of an email thread, using Claude Haiku for cost efficiency."""
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": (
                    "Summarize this email thread in 2-3 sentences. "
                    "Be specific about what was discussed and any decisions made. No emojis.\n\n"
                    f"Subject: {subject}\n\n{messages_text[:1500]}"
                ),
            }],
        )
        return response.content[0].text.strip()
    except Exception:
        logger.warning("Thread summary generation failed for: %s", subject)
        return f"Email thread about {subject}."


async def write_thread_to_vault(
    thread_id: str,
    subject: str,
    participants: list[str],
    message_count: int,
    last_message_at: datetime,
    messages: list[dict],
    user_emails: list[str],
    db: AsyncSession,
) -> str:
    """Write an email thread as a linked note to the Obsidian vault.

    Returns the absolute path of the written file, or an empty string when the
    vault is not configured or the write fails.
    """
    vault = vault_path()
    if vault is None:
        return ""

    # Fetch ALL connected account emails so we correctly exclude every address
    # the user owns — not just the single account that owns this thread.
    try:
        all_accounts_result = await db.execute(text("SELECT email FROM gmail_accounts"))
        all_user_emails = [row.email for row in all_accounts_result.fetchall()]
    except Exception:
        all_user_emails = list(user_emails)

    # Username prefixes (e.g. "yuvanadarshj") catch address variants like
    # "yuvanadarshj+filter@gmail.com" that simple equality would miss.
    user_usernames = [e.split("@")[0].lower() for e in all_user_emails]

    contact_email: str | None = None
    for participant in participants:
        p_lower = participant.lower()
        if any(ue.lower() in p_lower for ue in all_user_emails):
            continue
        if any(uu in p_lower.split("@")[0] for uu in user_usernames):
            continue
        contact_email = participant
        break

    # Self-sent thread: file under "Self" rather than the user's own name.
    if contact_email is None:
        contact_email = "self"
        contact_name = "Self"
    else:
        # Look up display name from contacts table
        try:
            contact_result = await db.execute(
                text("SELECT display_name FROM contacts WHERE email_address = :email"),
                {"email": contact_email},
            )
            contact_row = contact_result.fetchone()
            contact_name = (
                contact_row.display_name
                if contact_row and contact_row.display_name
                else contact_email.split("@")[0]
            )
        except Exception:
            contact_name = contact_email.split("@")[0]

    # Strip the email-address portion if the name still carries it, e.g.
    # "Max Scribner <max.scribner@assetliving.com>" → "Max Scribner". Without
    # this the directory name becomes "Max Scribner maxscribner" and the same
    # person ends up with two folders.
    if contact_name and "<" in contact_name:
        display_part = contact_name[: contact_name.index("<")].strip()
        if display_part:
            contact_name = display_part

    # Generate AI summary
    messages_text = "\n\n".join([
        f"From: {m.get('from_address', '')}\n{(m.get('body_text') or '')[:300]}"
        for m in messages[:5]
    ])
    summary = await generate_thread_summary(subject, messages_text)

    # Extract wikilinks, ensuring contact is always first; strip any link that
    # refers to the user themselves (e.g. "[[Yuvan yuvanadarshj]]").
    wikilinks = await extract_wikilinks(summary + " " + subject)
    wikilinks = [
        w for w in wikilinks
        if not any(uu in w.lower() for uu in user_usernames if len(uu) > 2)
    ]
    if contact_name not in wikilinks and contact_name != "Self":
        wikilinks.insert(0, contact_name)

    safe_subject = (
        re.sub(r"[^\w\s-]", "", subject)[:60].strip().replace(" ", "-") or "no-subject"
    )
    safe_contact = re.sub(r"[^\w\s-]", "", contact_name)[:40].strip() or "Unknown"

    # Reuse an existing folder whose normalized name matches, so a contact never
    # gets two near-identical directories (e.g. "Max-Scribner" vs "Max Scribner").
    emails_dir = vault / "Emails"
    normalized = re.sub(r"[^\w]", "", safe_contact).lower()
    existing_dir: str | None = None
    if emails_dir.exists():
        for entry in await asyncio.to_thread(lambda: list(os.listdir(emails_dir))):
            if re.sub(r"[^\w]", "", entry).lower() == normalized:
                existing_dir = entry
                break

    dir_path = emails_dir / (existing_dir or safe_contact)
    await asyncio.to_thread(dir_path.mkdir, parents=True, exist_ok=True)
    file_path = dir_path / f"{safe_subject}.md"

    # Format up to 5 most recent messages
    messages_md = ""
    for msg in messages[-5:]:
        received = msg.get("received_at")
        date_str = received.strftime("%B %d, %Y") if isinstance(received, datetime) else "Unknown date"
        sender = (msg.get("from_address") or "").split("@")[0]
        body = (msg.get("body_text") or "")[:500]
        messages_md += f"\n### {date_str} — {sender}\n{body}\n"

    related_links = "\n".join(f"- [[{w}]]" for w in wikilinks[:8])
    last_date = last_message_at.strftime("%B %d, %Y")

    note_content = (
        f"# {subject}\n\n"
        f"*Thread with [[{contact_name}]] · {message_count} messages · Last message: {last_date}*\n\n"
        f"## Summary\n{summary}\n\n"
        f"## Messages\n{messages_md}\n\n"
        f"## Related\n{related_links}\n"
    )

    async with aiofiles.open(str(file_path), "w", encoding="utf-8") as f:
        await f.write(note_content)

    return str(file_path)


async def export_threads_to_obsidian_background(account_id: int) -> None:
    """Write all email threads for an account to the Obsidian vault (background task).

    Clears the ``Emails/`` directory first so stale notes from a previous export
    (e.g. threads filed under the wrong contact name) don't persist.
    """
    from db.database import AsyncSessionLocal
    from services import settings_service

    # Wipe the Emails/ subtree so re-exports always start from a clean slate.
    emails_dir = vault_path()
    if emails_dir is not None:
        emails_dir = emails_dir / "Emails"
        if emails_dir.exists():
            await asyncio.to_thread(shutil.rmtree, str(emails_dir))
            logger.info("Cleared Emails/ directory for clean re-export")

    async with AsyncSessionLocal() as db:
        accounts_result = await db.execute(
            text("SELECT email FROM gmail_accounts WHERE id = :id"),
            {"id": account_id},
        )
        user_emails = [row.email for row in accounts_result.fetchall()]

        threads_result = await db.execute(
            text(
                """
                SELECT thread_id, subject, participants, message_count, last_message_at
                FROM email_threads
                WHERE account_id = :account_id
                ORDER BY last_message_at DESC
                """
            ),
            {"account_id": account_id},
        )
        thread_rows = threads_result.fetchall()
        total = len(thread_rows)
        logger.info("Exporting %s threads to Obsidian for account %s", total, account_id)

        progress_key = f"obsidian_export_progress_{account_id}"
        await settings_service.set_value(
            db, progress_key, json.dumps({"processed": 0, "total": total})
        )

        processed = 0
        for thread in thread_rows:
            try:
                messages_result = await db.execute(
                    text(
                        """
                        SELECT from_address, body_text, received_at
                        FROM emails
                        WHERE thread_id = :thread_id
                          AND account_id = :account_id
                        ORDER BY received_at ASC
                        LIMIT 10
                        """
                    ),
                    {"thread_id": thread.thread_id, "account_id": account_id},
                )
                messages = [dict(row._mapping) for row in messages_result.fetchall()]

                await write_thread_to_vault(
                    thread_id=thread.thread_id,
                    subject=thread.subject or "(no subject)",
                    participants=thread.participants or [],
                    message_count=thread.message_count or 0,
                    last_message_at=thread.last_message_at or datetime.utcnow(),
                    messages=messages,
                    user_emails=user_emails,
                    db=db,
                )
                processed += 1
                if processed % 50 == 0:
                    await settings_service.set_value(
                        db, progress_key, json.dumps({"processed": processed, "total": total})
                    )
                    logger.info("Obsidian export: %s/%s threads written", processed, total)
            except Exception:
                logger.warning("Failed to write thread %s to Obsidian", thread.thread_id)
                continue

        await settings_service.set_value(
            db, progress_key, json.dumps({"processed": total, "total": total, "done": True})
        )
        logger.info("Obsidian export complete for account %s: %s threads", account_id, total)


# ---------------------------------------------------------------------------
# Contact vault writer
# ---------------------------------------------------------------------------


async def write_contact_to_vault(
    email_address: str,
    display_name: str | None,
    email_count: int,
    last_contacted: datetime | None,
    db: AsyncSession,
) -> str:
    """Write a contact profile as a linked note to the Obsidian vault.

    Returns the absolute path of the written file, or an empty string when the
    vault is not configured.
    """
    vault = vault_path()
    if vault is None:
        return ""

    contact_name = display_name or email_address.split("@")[0]
    safe_name = re.sub(r"[^\w\s-]", "", contact_name)[:60].strip() or "Unknown"

    # Find email subjects involving this contact for thread linking
    try:
        threads_result = await db.execute(
            text(
                """
                SELECT DISTINCT subject, thread_id
                FROM emails
                WHERE from_address = :email
                   OR :email = ANY(to_addresses)
                ORDER BY subject
                LIMIT 10
                """
            ),
            {"email": email_address},
        )
        threads = [dict(row._mapping) for row in threads_result.fetchall()]
    except Exception:
        threads = []

    # Extract topics from thread subjects
    subjects_text = " ".join((t.get("subject") or "") for t in threads)
    topics = await extract_wikilinks(subjects_text) if subjects_text.strip() else []

    last_date = last_contacted.strftime("%B %d, %Y") if last_contacted else "Unknown"

    thread_links = (
        "\n".join(
            "- [[{}]]".format(
                re.sub(r"[^\w\s-]", "", t.get("subject") or "no-subject")[:60]
                .strip()
                .replace(" ", "-")
            )
            for t in threads
        )
        or "No threads recorded."
    )

    note_content = (
        f"# {contact_name}\n\n"
        f"*{email_address} · {email_count} emails · Last contacted: {last_date}*\n\n"
        f"## About\n"
        f"{contact_name} is a contact you've exchanged {email_count} emails with.\n"
        f"Last contacted: {last_date}\n\n"
        f"## Email Threads\n{thread_links}\n"
    )
    if topics:
        related_links = "\n".join(f"- [[{t}]]" for t in topics[:8])
        note_content += f"\n## Related\n{related_links}\n"

    dir_path = vault / "Contacts"
    await asyncio.to_thread(dir_path.mkdir, parents=True, exist_ok=True)
    file_path = dir_path / f"{safe_name}.md"

    async with aiofiles.open(str(file_path), "w", encoding="utf-8") as f:
        await f.write(note_content)

    return str(file_path)


async def export_contacts_to_obsidian_background() -> None:
    """Write all contacts to the Obsidian vault (background task).

    Clears the ``Contacts/`` directory first so renamed or stale profiles from a
    previous export don't linger alongside the freshly written ones.
    """
    from db.database import AsyncSessionLocal
    from services import settings_service

    # Wipe the Contacts/ subtree so re-exports always start clean.
    contacts_root = vault_path()
    if contacts_root is not None:
        contacts_root = contacts_root / "Contacts"
        if contacts_root.exists():
            await asyncio.to_thread(shutil.rmtree, str(contacts_root))
            logger.info("Cleared Contacts/ directory for clean re-export")

    async with AsyncSessionLocal() as db:
        contacts_result = await db.execute(
            text(
                """
                SELECT email_address, display_name, email_count, last_contacted
                FROM contacts
                ORDER BY email_count DESC
                """
            )
        )
        contacts = contacts_result.fetchall()
        total = len(contacts)
        logger.info("Exporting %s contacts to Obsidian", total)

        await settings_service.set_value(
            db, "obsidian_contacts_export_progress", json.dumps({"processed": 0, "total": total})
        )

        processed = 0
        for contact in contacts:
            try:
                await write_contact_to_vault(
                    email_address=contact.email_address,
                    display_name=contact.display_name,
                    email_count=contact.email_count or 0,
                    last_contacted=contact.last_contacted,
                    db=db,
                )
                processed += 1
                if processed % 100 == 0:
                    await settings_service.set_value(
                        db,
                        "obsidian_contacts_export_progress",
                        json.dumps({"processed": processed, "total": total}),
                    )
                    logger.info("Contacts export: %s/%s written", processed, total)
            except Exception:
                logger.warning("Failed to write contact %s to Obsidian", contact.email_address)
                continue

        await settings_service.set_value(
            db,
            "obsidian_contacts_export_progress",
            json.dumps({"processed": total, "total": total, "done": True}),
        )
        logger.info("Contacts Obsidian export complete: %s contacts", total)
