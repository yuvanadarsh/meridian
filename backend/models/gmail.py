"""Pydantic request/response models for the Gmail and onboarding endpoints."""

from typing import Literal

from pydantic import BaseModel


class SweepOptions(BaseModel):
    """How much history to sweep for an account.

    - ``all``   — every message in the mailbox
    - ``count`` — the most recent ``count`` messages
    - ``since`` — messages received on/after ``since_date`` (YYYY-MM-DD)

    Out-of-range values self-correct: Gmail returns fewer results than asked
    when the mailbox is smaller, so an oversized count or early date sweeps all.
    """

    mode: Literal["all", "count", "since"] = "all"
    count: int | None = None
    since_date: str | None = None
