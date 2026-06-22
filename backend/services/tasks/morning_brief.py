"""Morning brief task — pre-build and cache the daily digest.

Wraps the existing digest builder so it runs as a registered, reschedulable task
instead of the old hardcoded digest scheduler. Building it ahead of time means
the Brief panel loads instantly when the user opens Meridian in the morning.
"""

import logging

from .base import BaseTask

logger = logging.getLogger(__name__)


class MorningBriefTask(BaseTask):
    """Build the daily digest (news, stocks, calendar, email summary) and cache it."""

    name = "Morning Brief"
    description = "Builds the daily digest — news, stocks, calendar, and email summary"
    default_schedule = "08:00"
    default_days = "daily"

    async def run(self, db) -> dict:
        from services import digest_service

        digest = await digest_service.build_digest(db)
        await digest_service.save_digest_cache(db, digest)
        return {
            "status": "success",
            "summary": "Morning brief built and cached",
            "data": digest,
        }
