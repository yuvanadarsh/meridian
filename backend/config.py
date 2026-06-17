"""Application configuration.

All secrets and machine-specific values are read from environment variables
(loaded from .env in development). Nothing is hardcoded.
"""

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _BACKEND_DIR.parent

# Look for .env in both backend/ and the repo root so the same code works
# whether run from backend/, the repo root, or Docker (where the file is
# absent and real environment variables are used instead). Repo root wins.
_ENV_FILES = (str(_BACKEND_DIR / ".env"), str(_ROOT_DIR / ".env"))


class Settings(BaseSettings):
    """Strongly-typed settings sourced from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Claude API
    anthropic_api_key: str = ""

    # ElevenLabs
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""

    # VoyageAI
    voyage_api_key: str = ""

    # PostgreSQL (local install)
    postgres_db: str = "meridian"
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_host: str = "host.docker.internal"
    postgres_port: int = 5432

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Obsidian
    obsidian_vault_path: str = ""

    # App
    frontend_url: str = "http://localhost:5173"
    api_url: str = "http://localhost:8000"

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection string using the asyncpg driver.

        User and password are URL-encoded so special characters don't break
        the DSN.
        """
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (read the environment only once)."""
    return Settings()
