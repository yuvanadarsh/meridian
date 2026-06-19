"""Meridian FastAPI application entry point.

Wires CORS for the local Vite frontend, includes all routers, and verifies the
database connection on startup via the lifespan handler.
"""

import asyncio
import logging
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
from services import digest_service
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


async def run_digest_scheduler() -> None:
    """Pre-build the daily digest at the user's scheduled time, in their timezone.

    Checks once a minute whether the local time matches the ``digest_schedule``
    setting and no digest is cached for today; if so, builds and caches it so the
    Brief panel loads instantly when the user opens Meridian in the morning.
    """
    while True:
        await asyncio.sleep(60)
        try:
            async with AsyncSessionLocal() as db:
                time_row = (
                    await db.execute(
                        text("SELECT value FROM user_settings WHERE key = 'digest_schedule'")
                    )
                ).fetchone()
                if not time_row:
                    continue
                tz_row = (
                    await db.execute(
                        text("SELECT value FROM user_settings WHERE key = 'timezone'")
                    )
                ).fetchone()

                user_tz = ZoneInfo(tz_row.value if tz_row else "America/New_York")
                now_local = datetime.now(user_tz)
                target_h, target_m = (int(part) for part in time_row.value.split(":"))

                if now_local.hour == target_h and now_local.minute == target_m:
                    cached = (
                        await db.execute(
                            text("SELECT id FROM digest_cache WHERE cache_date = CURRENT_DATE")
                        )
                    ).fetchone()
                    if not cached:
                        logger.info("Running scheduled digest for %s", now_local.date())
                        digest = await digest_service.build_digest(db)
                        await digest_service.save_digest_cache(db, digest)
        except Exception:  # noqa: BLE001 — never let the scheduler loop die
            logger.exception("Digest scheduler error")


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
        await obsidian_service.scan_vault_on_startup()
        background_tasks.append(asyncio.create_task(obsidian_service.watch_vault()))
        background_tasks.append(asyncio.create_task(obsidian_service.vectorize_notes_loop()))
        logger.info("Obsidian vault watcher + note vectorizer started")

    # Pre-build the daily digest at the user's scheduled local time.
    background_tasks.append(asyncio.create_task(run_digest_scheduler()))
    logger.info("Digest scheduler started")

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
