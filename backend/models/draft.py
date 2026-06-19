"""Pydantic request/response models for the drafts endpoints."""

from datetime import datetime

from pydantic import BaseModel


class DraftGenerateRequest(BaseModel):
    """Parameters for generating a draft email in the user's voice."""

    account_id: int
    to_email: str
    subject: str
    context: str
    thread_email_id: int | None = None


class DraftEdit(BaseModel):
    """User edit to a draft's body before sending."""

    body: str


class DraftOut(BaseModel):
    """A stored draft as returned to the frontend."""

    id: int
    account_id: int | None
    to_email: str | None
    subject: str | None
    body: str | None
    thread_email_id: int | None
    status: str
    created_at: datetime
    updated_at: datetime
