"""Google Calendar routes: sync and event queries.

Implemented in the calendar sync build step.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/calendar", tags=["calendar"])
