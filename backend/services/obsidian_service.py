"""Obsidian vault integration — Meridian's long-term memory layer.

This module writes conversation exchanges into daily notes and extracts
wikilinks so the vault graph grows over time. The vault location always comes
from the ``OBSIDIAN_VAULT_PATH`` environment variable — never hardcoded. When
it is unset, every operation degrades to a no-op so chat still works.

Vault ingestion and RAG retrieval build on this module in later steps.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

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
