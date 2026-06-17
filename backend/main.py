"""Meridian FastAPI application entry point.

Wires CORS for the local Vite frontend, includes all routers, and verifies the
database connection on startup via the lifespan handler.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import get_settings
from db.database import check_connection
from routers import calendar, chat, gmail, health, obsidian, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("meridian")

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Test DB connectivity on startup; log the result but still boot the API."""
    try:
        await check_connection()
        logger.info("Database connection OK (%s)", settings.postgres_db)
    except Exception as exc:  # noqa: BLE001 — boot anyway so /health can report it
        logger.error("Database connection FAILED: %s", exc)
    yield


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
