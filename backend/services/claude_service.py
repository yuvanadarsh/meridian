"""Shared Claude API client and helpers.

The project standard model is ``claude-sonnet-4-6`` (see CLAUDE.md) — used for
reasoning, drafting, and triage classification.
"""

import logging
from datetime import date

from anthropic import AsyncAnthropic
from anthropic.types import Message, Usage

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Project standard model. Defined once so every caller stays in sync.
MODEL = "claude-sonnet-4-6"


def build_system_prompt(
    *,
    calendar_context: str = "",
    obsidian_context: str = "",
    today: str | None = None,
) -> str:
    """Assemble the chat system prompt.

    Concise, voice-first rules followed by any calendar / Obsidian context.
    Sections are omitted entirely when empty so the prompt stays tight.
    """
    today_date = today or date.today().isoformat()
    prompt = (
        f"You are Meridian, a personal AI assistant. Today is {today_date}.\n\n"
        "Rules:\n"
        "- Be direct and concise. Answer in 1-3 sentences unless detail is explicitly requested.\n"
        "- No emojis ever.\n"
        "- No markdown formatting in responses — plain text only, since responses are spoken aloud.\n"
        "- Never suggest the user contact a developer or admin. You are the assistant.\n"
        "- Never claim you lack access to calendar or email data without first checking the context provided below.\n"
        "- You cannot create, edit, or delete calendar events or send emails — say so plainly if asked."
    )
    for section in (calendar_context, obsidian_context):
        if section:
            prompt += "\n\n" + section
    return prompt

_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    """Return a lazily-created, shared async Anthropic client."""
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def extract_text(message: Message) -> str:
    """Concatenate the text blocks of a Claude response into a single string."""
    return "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()


async def chat(
    *, system: str, messages: list[dict], max_tokens: int = 2048
) -> tuple[str, Usage]:
    """Send a conversation to Claude; return the reply text and token usage."""
    client = get_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return extract_text(response), response.usage
