"""Supercharge import: parse AI chat exports into the memory layer.

Accepts Claude, ChatGPT, and Gemini conversation exports, normalizes each into a
common ``{title, date, exchanges}`` shape, and writes one note per conversation
to the PostgreSQL ``notes`` table (embedded immediately), so the user's past AI
conversations become part of Meridian's memory and are searchable via RAG.
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text

from db.database import AsyncSessionLocal
from services import memory_service

logger = logging.getLogger(__name__)

# Characters not allowed in filenames on common filesystems.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\n\r\t]')


def detect_provider(data) -> str:
    """Identify the export format from its structure: claude, chatgpt, or gemini."""
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if "chat_messages" in data[0]:
            return "claude"
        if "mapping" in data[0]:
            return "chatgpt"
    return "gemini"


def _safe_filename(title: str) -> str:
    """Sanitize a conversation title for use as a filename."""
    cleaned = _UNSAFE_FILENAME.sub(" ", title or "Untitled").strip()
    return (cleaned or "Untitled")[:120]


def _iso_date(value) -> str:
    """Best-effort convert a timestamp (epoch or ISO string) to YYYY-MM-DD."""
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (ValueError, OSError, TypeError):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _pair_exchanges(turns: list[tuple[str, str]]) -> list[dict]:
    """Pair an ordered list of (role, text) turns into {human, assistant} exchanges."""
    exchanges: list[dict] = []
    current: dict | None = None
    for role, content in turns:
        content = (content or "").strip()
        if not content:
            continue
        if role == "human":
            if current:
                exchanges.append(current)
            current = {"human": content, "assistant": ""}
        elif role == "assistant" and current is not None:
            # Concatenate consecutive assistant turns into one reply.
            current["assistant"] = (current["assistant"] + "\n\n" + content).strip()
    if current:
        exchanges.append(current)
    return exchanges


async def parse_claude_export(data: list) -> list[dict]:
    """Parse a Claude ``conversations.json`` export."""
    conversations = []
    for conv in data:
        turns: list[tuple[str, str]] = []
        for msg in conv.get("chat_messages", []):
            role = "human" if msg.get("sender", msg.get("role")) == "human" else "assistant"
            blocks = msg.get("content") or []
            if isinstance(blocks, list):
                text_content = "".join(
                    b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                text_content = str(blocks)
            if not text_content:
                text_content = msg.get("text", "")
            turns.append((role, text_content))
        conversations.append(
            {
                "title": conv.get("name") or "Untitled",
                "date": _iso_date(conv.get("created_at")),
                "exchanges": _pair_exchanges(turns),
            }
        )
    return conversations


async def parse_chatgpt_export(data: list) -> list[dict]:
    """Parse a ChatGPT ``conversations.json`` export (mapping tree)."""
    conversations = []
    for conv in data:
        mapping = conv.get("mapping", {})
        messages = []
        for node in mapping.values():
            msg = node.get("message")
            if not msg:
                continue
            author = (msg.get("author") or {}).get("role")
            if author not in ("user", "assistant"):
                continue
            parts = (msg.get("content") or {}).get("parts") or []
            text_content = "\n".join(p for p in parts if isinstance(p, str))
            messages.append((msg.get("create_time") or 0, author, text_content))
        messages.sort(key=lambda m: m[0])
        turns = [("human" if role == "user" else "assistant", content) for _, role, content in messages]
        conversations.append(
            {
                "title": conv.get("title") or "Untitled",
                "date": _iso_date(conv.get("create_time")),
                "exchanges": _pair_exchanges(turns),
            }
        )
    return conversations


async def parse_gemini_export(data) -> list[dict]:
    """Parse a Gemini export from Google Takeout (tolerant, best-effort).

    Takeout's Gemini activity is a list of records, each typically a single
    prompt with a title and optional response text. We treat each record as a
    one-exchange conversation.
    """
    records = data if isinstance(data, list) else data.get("activitySegments") or []
    conversations = []
    for record in records:
        if not isinstance(record, dict):
            continue
        prompt = record.get("title") or record.get("prompt") or ""
        # Common Takeout shape: response under "subtitles" or "geminiResponse".
        response = ""
        if isinstance(record.get("geminiResponse"), str):
            response = record["geminiResponse"]
        elif isinstance(record.get("subtitles"), list):
            response = " ".join(
                s.get("name", "") for s in record["subtitles"] if isinstance(s, dict)
            )
        if not prompt and not response:
            continue
        conversations.append(
            {
                "title": (prompt[:60] or "Gemini conversation"),
                "date": _iso_date(record.get("time")),
                "exchanges": [{"human": prompt, "assistant": response}],
            }
        )
    return conversations


async def parse_export(data) -> tuple[str, list[dict]]:
    """Detect the provider and parse the export into normalized conversations."""
    provider = detect_provider(data)
    if provider == "claude":
        return provider, await parse_claude_export(data)
    if provider == "chatgpt":
        return provider, await parse_chatgpt_export(data)
    return provider, await parse_gemini_export(data)


def _render_markdown(provider: str, conversation: dict) -> str:
    """Render one normalized conversation as note content."""
    lines = [
        f"# {conversation['title']}",
        f"*Imported from {provider} — {conversation['date']}*",
        "",
        "## Conversation",
        "",
    ]
    for exchange in conversation["exchanges"]:
        if exchange.get("human"):
            lines.append(f"**You:** {exchange['human']}")
            lines.append("")
        if exchange.get("assistant"):
            lines.append(f"**AI:** {exchange['assistant']}")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


async def _write_conversation(provider: str, conversation: dict, db) -> bool:
    """Write a single conversation to the memory layer. Returns True on success."""
    title = f"AI Conversations/{provider}/{_safe_filename(conversation['title'])}"
    await memory_service.write_note(
        title=title,
        content=_render_markdown(provider, conversation),
        note_type="general",
        source_id=None,
        wikilinks=[],
        db=db,
    )
    return True


async def process_import(import_id: int, provider: str, conversations: list[dict]) -> None:
    """Background task: write every conversation to memory, tracking progress."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE supercharge_imports SET status = 'processing' WHERE id = :id"),
            {"id": import_id},
        )
        await db.commit()

    processed = 0
    try:
        for conversation in conversations:
            try:
                async with AsyncSessionLocal() as db:
                    await _write_conversation(provider, conversation, db)
            except Exception:  # noqa: BLE001 — skip one bad conversation, keep going
                logger.exception("Failed to write a %s conversation", provider)
            processed += 1
            # Persist progress every 10 conversations so the UI can follow along.
            if processed % 10 == 0 or processed == len(conversations):
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        text(
                            "UPDATE supercharge_imports SET processed_conversations = :n "
                            "WHERE id = :id"
                        ),
                        {"n": processed, "id": import_id},
                    )
                    await db.commit()

        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE supercharge_imports SET status = 'complete', "
                    "processed_conversations = :n WHERE id = :id"
                ),
                {"n": processed, "id": import_id},
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Supercharge import %s failed", import_id)
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("UPDATE supercharge_imports SET status = 'error' WHERE id = :id"),
                {"id": import_id},
            )
            await db.commit()


async def create_import(db, provider: str, filename: str, total: int) -> int:
    """Create a supercharge_imports row and return its id."""
    result = await db.execute(
        text(
            """
            INSERT INTO supercharge_imports (provider, filename, total_conversations, status)
            VALUES (:provider, :filename, :total, 'pending')
            RETURNING id
            """
        ),
        {"provider": provider, "filename": filename, "total": total},
    )
    import_id = result.scalar_one()
    await db.commit()
    return import_id


async def get_progress(db, import_id: int) -> dict | None:
    """Return an import's progress row, or None if not found."""
    result = await db.execute(
        text(
            """
            SELECT id, provider, filename, total_conversations,
                   processed_conversations, status, created_at
            FROM supercharge_imports WHERE id = :id
            """
        ),
        {"id": import_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_imports(db) -> list[dict]:
    """Return all past imports, newest first."""
    result = await db.execute(
        text(
            """
            SELECT id, provider, filename, total_conversations,
                   processed_conversations, status, created_at
            FROM supercharge_imports ORDER BY created_at DESC
            """
        )
    )
    return [dict(row) for row in result.mappings().all()]
