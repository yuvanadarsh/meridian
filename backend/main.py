"""Meridian FastAPI application entry point.

Wires CORS for the local Vite frontend, includes all routers, and verifies the
database connection on startup via the lifespan handler.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import get_settings
from db.database import AsyncSessionLocal, check_connection
from services.tasks import get_task
from routers import (
    calendar,
    chat,
    contacts,
    digest,
    drafts,
    gmail,
    health,
    obsidian,
    settings as settings_router,
    supercharge,
    voice,
)
from services import obsidian_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("meridian")

settings = get_settings()


# Email sync polls Gmail on its own cadence, independent of the clock-based
# tasks, so new mail shows up within ~15 minutes without any AI calls.
EMAIL_POLL_INTERVAL_SECONDS = 15 * 60

# Days a task may run, mapped to a predicate over datetime.weekday() (Mon=0).
_DAY_MATCHERS = {
    "daily": lambda wd: True,
    "weekdays": lambda wd: wd < 5,
    "weekends": lambda wd: wd >= 5,
}


async def run_task_scheduler() -> None:
    """Generic scheduler — runs registered tasks from the ``scheduled_tasks`` table.

    Wakes once a minute. The email poll runs on its own 15-minute interval; every
    other enabled task runs when the user's local time matches its ``schedule_time``
    and it hasn't already run today (compared against the user's local date, not
    the DB's UTC ``CURRENT_DATE``). Each run's status and summary are written back
    so the Settings UI can show when a task last ran.
    """
    last_email_poll = 0.0

    while True:
        await asyncio.sleep(60)
        try:
            # Email poll on its own interval, regardless of the clock.
            if time.time() - last_email_poll >= EMAIL_POLL_INTERVAL_SECONDS:
                last_email_poll = time.time()
                task = get_task("email_poll")
                if task:
                    async with AsyncSessionLocal() as db:
                        result = await task.safe_run(db)
                        await _record_task_run(db, "email_poll", result)

            async with AsyncSessionLocal() as db:
                tz_row = (
                    await db.execute(
                        text("SELECT value FROM user_settings WHERE key = 'timezone'")
                    )
                ).fetchone()
                user_tz = ZoneInfo(tz_row.value if tz_row else "America/New_York")
                now_local = datetime.now(user_tz)
                today_local = now_local.date()

                due = await db.execute(
                    text(
                        """
                        SELECT id, task_key, schedule_time, schedule_days
                        FROM scheduled_tasks
                        WHERE enabled = TRUE
                          AND task_key != 'email_poll'
                          AND (last_run_at IS NULL OR DATE(last_run_at) < :today)
                        """
                    ),
                    {"today": today_local},
                )
                for row in due.fetchall():
                    if not _DAY_MATCHERS.get(row.schedule_days, _DAY_MATCHERS["daily"])(
                        now_local.weekday()
                    ):
                        continue
                    try:
                        target_h, target_m = (int(p) for p in row.schedule_time.split(":"))
                    except (ValueError, AttributeError):
                        continue
                    if now_local.hour == target_h and now_local.minute == target_m:
                        task = get_task(row.task_key)
                        if task:
                            result = await task.safe_run(db)
                            await _record_task_run(db, row.task_key, result)
        except Exception:  # noqa: BLE001 — never let the scheduler loop die
            logger.exception("Task scheduler error")


async def _record_task_run(db, task_key: str, result: dict) -> None:
    """Persist a task's last run time, status, and summary back to the table."""
    await db.execute(
        text(
            """
            UPDATE scheduled_tasks
            SET last_run_at = NOW(),
                last_run_status = :status,
                last_run_summary = :summary
            WHERE task_key = :task_key
            """
        ),
        {
            "status": result.get("status", "error"),
            "summary": result.get("summary", ""),
            "task_key": task_key,
        },
    )
    await db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Verify the DB on startup and run the Obsidian background tasks for the app's life."""
    try:
        await check_connection()
        logger.info("Database connection OK (%s)", settings.postgres_db)
    except Exception as exc:  # noqa: BLE001 — boot anyway so /health can report it
        logger.error("Database connection FAILED: %s", exc)

    background_tasks: list[asyncio.Task] = []
    if obsidian_service.vault_path() is not None:
        await obsidian_service.cleanup_vault_root_stubs()
        await obsidian_service.scan_vault_on_startup()
        background_tasks.append(asyncio.create_task(obsidian_service.watch_vault()))
        background_tasks.append(asyncio.create_task(obsidian_service.vectorize_notes_loop()))
        logger.info("Obsidian vault watcher + note vectorizer started")

    # Generic scheduler runs registered tasks (morning brief, email poll,
    # afternoon review, calendar sync) from the scheduled_tasks table.
    background_tasks.append(asyncio.create_task(run_task_scheduler()))
    logger.info("Task scheduler started")

    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)


app = FastAPI(title="Meridian", version="0.1.0", lifespan=lifespan)

# The frontend is a separate origin (Vite dev server) during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(gmail.router)
app.include_router(contacts.router)
app.include_router(calendar.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(obsidian.router)
app.include_router(drafts.router)
app.include_router(digest.router)
app.include_router(settings_router.router)
app.include_router(contacts.router)
app.include_router(supercharge.router)


# All failures return the shape { error: string, detail?: string }.
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Validation error", "detail": str(exc.errors())},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
