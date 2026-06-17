"""Gmail routes: OAuth, account management, sweep, and triage.

Implemented across the Gmail OAuth, sweep, and triage build steps.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/gmail", tags=["gmail"])
