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
    email_context: str = "",
    accounts: list[dict] | None = None,
    tone: str = "concise",
    today: str | None = None,
    allow_draft: bool = False,
) -> str:
    """Assemble the chat system prompt.

    Concise, voice-first rules followed by any calendar / email / Obsidian
    context. Sections are omitted entirely when empty so the prompt stays tight.
    The ``tone`` setting controls response length/personality, and ``accounts``
    lets Claude pick a valid sending account for draft/calendar actions.

    ``allow_draft`` gates the email-drafting instructions. The caller only sets
    it when the user's message is an explicit draft request (see
    ``chat.is_draft_intent``). When False, the draft protocol is stripped
    entirely so Claude cannot accidentally emit a ``DRAFT_EMAIL:`` token in
    response to a plain question that merely mentions email.
    """
    today_date = today or date.today().isoformat()
    capabilities = (
        "draft emails and create calendar events" if allow_draft else "create calendar events"
    )
    prompt = (
        f"You are Meridian, a personal AI assistant. Today is {today_date}.\n\n"
        "Rules:\n"
        f"- {_TONE_RULES.get(tone, _TONE_RULES['concise'])}\n"
        "- No emojis ever.\n"
        "- No markdown formatting in responses — plain text only, since responses are spoken aloud.\n"
        "- Never suggest the user contact a developer or admin. You are the assistant.\n"
        "- Never claim you lack access to calendar or email data without first checking the context provided below.\n"
        f"- You can {capabilities} when asked, using the action protocol below."
    )
    prompt += "\n\n" + _action_protocol(accounts or [], include_draft=allow_draft)
    if email_context:
        prompt += "\n\nRELEVANT EMAILS:\n" + email_context
    for section in (calendar_context, obsidian_context):
        if section:
            prompt += "\n\n" + section
    return prompt


# Tone presets, selectable from Settings and persisted in user_settings.
_TONE_RULES = {
    "concise": "Be direct and concise. Answer in 1-3 sentences unless detail is explicitly requested.",
    "moderate": "Be clear and helpful. Answer in up to a short paragraph with some supporting detail.",
    "conversational": "Be warm and natural, like a back-and-forth conversation. Show a little personality while staying useful.",
}


def _action_protocol(accounts: list[dict], *, include_draft: bool = False) -> str:
    """Instructions that let Claude trigger draft/calendar actions via tokens.

    ``chat.py`` intercepts the emitted ``DRAFT_EMAIL:`` / ``CALENDAR_CREATE:``
    line, performs the action, and replaces it with a clean confirmation. The
    ``DRAFT_EMAIL:`` instructions are only included when ``include_draft`` is
    True (an explicit draft request) — otherwise they are omitted so Claude
    cannot accidentally draft an email in response to a plain email question.
    """
    if accounts:
        account_lines = "\n".join(
            f"  - account_id {a['id']}: {a['email']}" for a in accounts
        )
        accounts_block = f"Connected accounts:\n{account_lines}\n"
        default_id = accounts[0]["id"]
    else:
        accounts_block = "No connected accounts.\n"
        default_id = 1

    draft_block = ""
    if include_draft:
        draft_block = (
            "If the user asks you to draft, write, or compose an email or reply, respond with ONLY "
            "this JSON on the first line, then a short confirmation sentence:\n"
            'DRAFT_EMAIL:{"account_id":' + str(default_id) + ',"to_email":"...","subject":"...","context":"what the email should say","thread_email_id":null}\n'
            "Use the RELEVANT EMAILS context to fill to_email when replying to someone. "
            "If you cannot determine a recipient, leave to_email as an empty string.\n"
        )

    return (
        "ACTIONS:\n"
        f"{accounts_block}"
        f"{draft_block}"
        "If the user asks you to schedule, create, or add a calendar event, respond with ONLY this "
        "JSON on the first line, then your confirmation message:\n"
        'CALENDAR_CREATE:{"account_id":' + str(default_id) + ',"title":"...","start":"2026-06-19T15:00:00","end":"2026-06-19T16:00:00","description":""}\n'
        "Times are local (America/New_York), ISO 8601, no timezone suffix. Default events to one "
        "hour when the user gives only a start time.\n"
        "Only emit an action token when the user clearly requests that action."
    )

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
