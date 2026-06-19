"""Symmetric encryption for secrets stored in the database (provider API keys).

A Fernet key is derived from ``SECRET_KEY`` (env, ``openssl rand -hex 32``) so the
encryption key itself is never persisted. Raw plaintext keys are never logged or
returned by the API — only ``encrypt``/``decrypt`` touch them.
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from config import get_settings


def _fernet() -> Fernet:
    """Build a Fernet instance from a SHA-256 of the configured SECRET_KEY."""
    secret = get_settings().secret_key
    if not secret:
        raise RuntimeError(
            "SECRET_KEY is not configured — set it in .env (openssl rand -hex 32) "
            "before storing provider API keys."
        )
    # Fernet needs a 32-byte urlsafe-base64 key; derive one deterministically.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for at-rest storage; returns a urlsafe token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt`."""
    return _fernet().decrypt(token.encode()).decode()
