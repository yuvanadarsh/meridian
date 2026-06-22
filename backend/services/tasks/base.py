"""Base class for Meridian's scheduled background tasks.

Every task — morning brief, email poll, afternoon review, calendar sync —
subclasses :class:`BaseTask` and implements :meth:`run`. The generic scheduler
in ``main.py`` reads the ``scheduled_tasks`` table, looks each task up in the
registry (``services.tasks.get_task``), and calls :meth:`safe_run`, which wraps
:meth:`run` with uniform logging and error handling so one failing task never
takes the scheduler loop down.

Adding a new task is two steps: write one subclass file here, then register it
in ``services/tasks/__init__.py``.
"""

from abc import ABC, abstractmethod

import logging

logger = logging.getLogger(__name__)


class BaseTask(ABC):
    """A unit of scheduled work with a uniform run/result contract."""

    name: str = ""
    description: str = ""
    default_schedule: str = "08:00"  # HH:MM (or "*/15" for interval tasks)
    default_days: str = "daily"      # 'daily', 'weekdays', 'weekends'

    @abstractmethod
    async def run(self, db) -> dict:
        """Execute the task.

        Returns a dict shaped ``{"status": "success"|"error", "summary": str,
        "data": dict}``.
        """

    async def safe_run(self, db) -> dict:
        """Run the task, never raising — logs and returns an error result instead."""
        try:
            logger.info("Task starting: %s", self.name)
            result = await self.run(db)
            logger.info("Task complete: %s — %s", self.name, result.get("summary", ""))
            return result
        except Exception as exc:  # noqa: BLE001 — one bad task must not kill the loop
            logger.error("Task failed: %s — %s", self.name, exc, exc_info=True)
            return {"status": "error", "summary": str(exc), "data": {}}
