"""Shared Claude API client and helpers.

The project standard model is ``claude-sonnet-4-6`` (see CLAUDE.md) — used for
reasoning, drafting, and triage classification.
"""

import logging

from anthropic import AsyncAnthropic
from anthropic.types import Message

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Project standard model. Defined once so every caller stays in sync.
MODEL = "claude-sonnet-4-6"

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
