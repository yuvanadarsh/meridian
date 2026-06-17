"""Gmail / Google Calendar OAuth and account management.

A single OAuth grant covers both Gmail (read / modify / send) and Calendar
(read / events). The resulting credentials are stored as JSONB in
``gmail_accounts.oauth_token`` and auto-refreshed whenever they're loaded.
"""

import json
import logging
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings

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
