"""Gmail / Google Calendar OAuth and account management.

A single OAuth grant covers both Gmail (read / modify / send) and Calendar
(read / events). The resulting credentials are stored as JSONB in
``gmail_accounts.oauth_token`` and auto-refreshed whenever they're loaded.
"""

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.database import AsyncSessionLocal

# Google frequently returns scopes in a different order (and adds `openid`),
# which otherwise makes oauthlib raise a scope-change warning as an error.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

logger = logging.getLogger(__name__)
settings = get_settings()

# One consent covers everything Meridian needs from Google.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

REDIRECT_URI = f"{settings.api_url}/gmail/callback"


def _client_config() -> dict:
    """OAuth client config assembled from environment settings."""
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }


def build_auth_url(label: str) -> str:
    """Return the Google consent URL. ``label`` round-trips via the OAuth state."""
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force a refresh_token to be issued
        state=label,
    )
    return auth_url


def exchange_code(code: str) -> Credentials:
    """Exchange an authorization code for OAuth credentials (blocking)."""
    flow = Flow.from_client_config(
        _client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(code=code)
    return flow.credentials


def get_account_email(creds: Credentials) -> str:
    """Look up the authenticated account's address via the Gmail profile."""
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def credentials_to_dict(creds: Credentials) -> dict:
    """Serialize credentials to a JSON-safe dict for storage."""
    return json.loads(creds.to_json())


async def upsert_account(
    db: AsyncSession, *, email: str, label: str, token: dict
) -> dict:
    """Insert or update a connected account, keyed by email address."""
    result = await db.execute(
        text(
            """
            INSERT INTO gmail_accounts (email, label, oauth_token)
            VALUES (:email, :label, CAST(:token AS jsonb))
            ON CONFLICT (email) DO UPDATE
                SET label = EXCLUDED.label,
                    oauth_token = EXCLUDED.oauth_token
            RETURNING id, email, label
            """
        ),
        {"email": email, "label": label, "token": json.dumps(token)},
    )
    await db.commit()
    return dict(result.mappings().one())


async def list_accounts(db: AsyncSession) -> list[dict]:
    """Return all connected accounts (without tokens)."""
    result = await db.execute(
        text(
            """
            SELECT id, email, label, last_synced_at
            FROM gmail_accounts
            ORDER BY id
            """
        )
    )
    return [dict(row) for row in result.mappings().all()]


async def load_credentials(db: AsyncSession, account_id: int) -> Credentials:
    """Load stored credentials for an account, refreshing them if expired.

    A refreshed token is written back to the database so the new access token
    is reused next time.
    """
    result = await db.execute(
        text("SELECT oauth_token FROM gmail_accounts WHERE id = :id"),
        {"id": account_id},
    )
    row = result.mappings().first()
    if row is None or not row["oauth_token"]:
        raise ValueError(f"No credentials stored for account {account_id}")

    token = row["oauth_token"]
    if isinstance(token, str):  # asyncpg returns JSONB as text
        token = json.loads(token)

    creds = Credentials.from_authorized_user_info(token, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        await db.execute(
            text(
                "UPDATE gmail_accounts SET oauth_token = CAST(:token AS jsonb) "
                "WHERE id = :id"
            ),
            {"token": creds.to_json(), "id": account_id},
        )
        await db.commit()
        logger.info("Refreshed OAuth token for account %s", account_id)

    return creds


# ---------------------------------------------------------------------------
# Email sweep
# ---------------------------------------------------------------------------

# Gmail allows ~6,000 quota units/min and ~50 concurrent requests per mailbox;
# messages.get costs 5 units each. These settings keep us well under both.
SWEEP_BATCH_SIZE = 25
SWEEP_DELAY_SECONDS = 0.1
MAX_RETRIES = 5
DEFAULT_MAX_MESSAGES = 500


def extract_body(payload: dict) -> str:
    """BFS traversal of the Gmail MIME payload tree.

    Prefers text/plain, falls back to text/html, returns "" if nothing found.
    Never assume payload.body.data holds the body — multipart emails nest it.
    """
    text_body = ""
    html_body = ""

    queue = [payload]
    while queue:
        part = queue.pop(0)
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")

        if data:
            try:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                if mime_type == "text/plain" and not text_body:
                    text_body = decoded
                elif mime_type == "text/html" and not html_body:
                    html_body = decoded
            except Exception:  # noqa: BLE001 — skip parts that fail to decode
                pass

        for sub_part in part.get("parts", []):
            queue.append(sub_part)

    return text_body or html_body or ""


def extract_header(headers: list, name: str) -> str:
    """Case-insensitive header lookup — Gmail is inconsistent with casing."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _parse_internal_date(internal_date: str | None) -> datetime | None:
    """Convert Gmail's internalDate (ms since epoch) to a naive UTC datetime."""
    if not internal_date:
        return None
    try:
        return datetime.fromtimestamp(
            int(internal_date) / 1000, tz=timezone.utc
        ).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


async def fetch_with_backoff(service, gmail_id: str, max_retries: int = MAX_RETRIES) -> dict:
    """messages.get with exponential backoff on 429 rate-limit errors."""
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(
                lambda: service.users()
                .messages()
                .get(userId="me", id=gmail_id, format="full")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            if "429" in str(exc) or "rateLimitExceeded" in str(exc):
                wait = 2**attempt
                logger.warning(
                    "Rate limited on %s, waiting %ss (attempt %s/%s)",
                    gmail_id,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait)
            else:
                raise
    raise RuntimeError(f"Max retries exceeded for message {gmail_id}")


async def _list_message_ids(service, max_messages: int) -> list[str]:
    """List up to ``max_messages`` message IDs, paginating as needed."""
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_messages:
        remaining = max_messages - len(ids)
        response = await asyncio.to_thread(
            lambda: service.users()
            .messages()
            .list(userId="me", maxResults=min(500, remaining), pageToken=page_token)
            .execute()
        )
        ids.extend(message["id"] for message in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return ids[:max_messages]


async def _store_email(db: AsyncSession, account_id: int, message: dict) -> bool:
    """Insert one parsed email. Returns True if newly stored, False if a dup."""
    payload = message.get("payload", {})
    headers = payload.get("headers", [])

    from_address = extract_header(headers, "From")[:255] or None
    to_raw = extract_header(headers, "To")
    to_addresses = [addr.strip() for addr in to_raw.split(",") if addr.strip()]

    result = await db.execute(
        text(
            """
            INSERT INTO emails (
                account_id, gmail_id, thread_id, from_address, to_addresses,
                subject, body_text, snippet, received_at, triage_status
            )
            VALUES (
                :account_id, :gmail_id, :thread_id, :from_address, :to_addresses,
                :subject, :body_text, :snippet, :received_at, 'pending'
            )
            ON CONFLICT (gmail_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "account_id": account_id,
            "gmail_id": message["id"],
            "thread_id": message.get("threadId"),
            "from_address": from_address,
            "to_addresses": to_addresses,
            "subject": extract_header(headers, "Subject") or None,
            "body_text": extract_body(payload),
            "snippet": message.get("snippet", ""),
            "received_at": _parse_internal_date(message.get("internalDate")),
        },
    )
    inserted = result.first() is not None
    await db.commit()
    return inserted


async def _save_progress(
    db: AsyncSession,
    account_id: int,
    *,
    status: str,
    total_estimated: int,
    fetched: int,
    stored: int,
    skipped: int,
    last_gmail_id: str | None = None,
) -> None:
    """Upsert the full sweep_progress row for an account."""
    await db.execute(
        text(
            """
            INSERT INTO sweep_progress (
                account_id, status, total_estimated, fetched, stored, skipped,
                last_gmail_id, error, updated_at
            )
            VALUES (
                :account_id, :status, :total_estimated, :fetched, :stored,
                :skipped, :last_gmail_id, NULL, NOW()
            )
            ON CONFLICT (account_id) DO UPDATE SET
                status = EXCLUDED.status,
                total_estimated = EXCLUDED.total_estimated,
                fetched = EXCLUDED.fetched,
                stored = EXCLUDED.stored,
                skipped = EXCLUDED.skipped,
                last_gmail_id = EXCLUDED.last_gmail_id,
                error = NULL,
                updated_at = NOW()
            """
        ),
        {
            "account_id": account_id,
            "status": status,
            "total_estimated": total_estimated,
            "fetched": fetched,
            "stored": stored,
            "skipped": skipped,
            "last_gmail_id": last_gmail_id,
        },
    )
    await db.commit()


async def mark_sweep_error(db: AsyncSession, account_id: int, message: str) -> None:
    """Flag the sweep as errored, preserving existing counters."""
    await db.execute(
        text(
            """
            INSERT INTO sweep_progress (account_id, status, error, updated_at)
            VALUES (:account_id, 'error', :error, NOW())
            ON CONFLICT (account_id) DO UPDATE SET
                status = 'error', error = :error, updated_at = NOW()
            """
        ),
        {"account_id": account_id, "error": message},
    )
    await db.commit()


async def get_sweep_progress(db: AsyncSession, account_id: int) -> dict:
    """Return the current sweep progress for an account."""
    result = await db.execute(
        text(
            """
            SELECT status, total_estimated, fetched, stored, skipped
            FROM sweep_progress WHERE account_id = :account_id
            """
        ),
        {"account_id": account_id},
    )
    row = result.mappings().first()
    if row is None:
        return {
            "status": "idle",
            "fetched": 0,
            "total_estimated": 0,
            "stored": 0,
            "skipped": 0,
        }
    return dict(row)


async def sweep_account(
    account_id: int, db: AsyncSession, max_messages: int = DEFAULT_MAX_MESSAGES
) -> dict:
    """Fetch and store an account's messages with rate limiting and backoff.

    Idempotent: re-running skips already-stored emails (ON CONFLICT DO NOTHING),
    so an interrupted sweep resumes simply by being started again.
    """
    creds = await load_credentials(db, account_id)
    service = await asyncio.to_thread(
        lambda: build("gmail", "v1", credentials=creds, cache_discovery=False)
    )

    await _save_progress(
        db, account_id, status="running", total_estimated=0, fetched=0, stored=0, skipped=0
    )

    message_ids = await _list_message_ids(service, max_messages)
    total = len(message_ids)

    fetched = stored = skipped = 0
    last_id: str | None = None

    for start in range(0, total, SWEEP_BATCH_SIZE):
        batch = message_ids[start : start + SWEEP_BATCH_SIZE]
        for gmail_id in batch:
            try:
                message = await fetch_with_backoff(service, gmail_id)
            except Exception as exc:  # noqa: BLE001 — log and skip one bad message
                logger.error("Failed to fetch message %s: %s", gmail_id, exc)
                continue

            fetched += 1
            last_id = gmail_id
            if await _store_email(db, account_id, message):
                stored += 1
            else:
                skipped += 1

            await asyncio.sleep(SWEEP_DELAY_SECONDS)

        # Persist progress at each batch boundary so the UI can follow along.
        await _save_progress(
            db,
            account_id,
            status="running",
            total_estimated=total,
            fetched=fetched,
            stored=stored,
            skipped=skipped,
            last_gmail_id=last_id,
        )

    await _save_progress(
        db,
        account_id,
        status="completed",
        total_estimated=total,
        fetched=fetched,
        stored=stored,
        skipped=skipped,
        last_gmail_id=last_id,
    )
    await db.execute(
        text("UPDATE gmail_accounts SET last_synced_at = NOW() WHERE id = :id"),
        {"id": account_id},
    )
    await db.commit()

    logger.info(
        "Sweep complete for account %s: fetched=%s stored=%s skipped=%s",
        account_id,
        fetched,
        stored,
        skipped,
    )
    return {"fetched": fetched, "stored": stored, "skipped": skipped}


async def run_sweep_background(
    account_id: int, max_messages: int = DEFAULT_MAX_MESSAGES
) -> None:
    """Entry point for FastAPI BackgroundTasks — owns its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await sweep_account(account_id, db, max_messages=max_messages)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background sweep failed for account %s", account_id)
            try:
                await mark_sweep_error(db, account_id, str(exc))
            except Exception:  # noqa: BLE001
                logger.exception("Could not record sweep error for account %s", account_id)
