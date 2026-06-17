"""CLI helper to connect a Google account to Meridian.

Usage:
    python scripts/setup_oauth.py --label personal

Opens a browser for Google OAuth, then stores the resulting token in the
gmail_accounts table. This is an alternative to the in-app Connections flow.

Requires ``http://localhost:8765/`` to be registered as an authorized redirect
URI on your OAuth client (Google Cloud Console).
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Make the backend package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402

from config import get_settings  # noqa: E402
from db.database import AsyncSessionLocal  # noqa: E402
from services import gmail_service  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("setup_oauth")

LOCAL_PORT = 8765


def run_oauth() -> Credentials:
    """Run the local-server OAuth flow and return credentials."""
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise SystemExit("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env")

    client_config = {
        "installed": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{LOCAL_PORT}/"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=gmail_service.SCOPES)
    return flow.run_local_server(port=LOCAL_PORT, prompt="consent")


async def store_account(label: str, creds: Credentials) -> str:
    """Persist the account + token in the database, return its email address."""
    email = gmail_service.get_account_email(creds)
    async with AsyncSessionLocal() as db:
        await gmail_service.upsert_account(
            db, email=email, label=label, token=gmail_service.credentials_to_dict(creds)
        )
    return email


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect a Google account to Meridian")
    parser.add_argument(
        "--label",
        required=True,
        choices=["personal", "school", "work", "professional"],
        help="Role to assign this account",
    )
    args = parser.parse_args()

    creds = run_oauth()
    email = asyncio.run(store_account(args.label, creds))
    logger.info("Connected %s as '%s'", email, args.label)


if __name__ == "__main__":
    main()
