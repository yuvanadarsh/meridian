"""Pydantic request/response models for the chat endpoints."""

from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    account_id: int | None = None


class ChatMessageOut(BaseModel):
    """A persisted chat turn, returned when pre-loading history."""

    role: str
    content: str
    created_at: datetime | None = None


class TokenUsage(BaseModel):
    input: int
    output: int
    total: int


class ChatResponse(BaseModel):
    response: str
    tokens: TokenUsage


class TokensToday(BaseModel):
    total: int
    input: int
    output: int
