"""Pydantic models for the Obsidian endpoints."""

from pydantic import BaseModel


class AppendExchange(BaseModel):
    """One conversation turn to append to today's daily note."""

    user_message: str
    assistant_message: str
