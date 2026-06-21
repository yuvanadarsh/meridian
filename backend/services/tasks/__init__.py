"""Task registry — maps a stable ``task_key`` to its :class:`BaseTask` subclass.

The ``scheduled_tasks`` table stores ``task_key`` values; the scheduler resolves
them to classes here. To add a task: implement a ``BaseTask`` subclass in this
package and add one line to ``TASK_REGISTRY``.
"""

from .base import BaseTask
from .afternoon_review import AfternoonEmailReviewTask
from .calendar_sync import CalendarSyncTask
from .email_poll import EmailPollTask
from .morning_brief import MorningBriefTask

TASK_REGISTRY: dict[str, type[BaseTask]] = {
    "morning_brief": MorningBriefTask,
    "email_poll": EmailPollTask,
    "afternoon_review": AfternoonEmailReviewTask,
    "calendar_sync": CalendarSyncTask,
}


def get_task(name: str) -> BaseTask | None:
    """Instantiate the task registered under ``name``, or None if unknown."""
    cls = TASK_REGISTRY.get(name)
    return cls() if cls else None


def list_tasks() -> list[dict]:
    """Describe every registered task type — for the scheduling UI's add form."""
    return [
        {
            "key": key,
            "name": cls.name,
            "description": cls.description,
            "default_schedule": cls.default_schedule,
            "default_days": cls.default_days,
        }
        for key, cls in TASK_REGISTRY.items()
    ]
