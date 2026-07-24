"""Encrypt schedule SSH credentials at rest (Fernet).

Master key sources (first match wins):
  1. ``NCCM_SECRETS_KEY`` environment variable (urlsafe base64, 32 bytes)
  2. File path from ``NCCM_SECRETS_KEY_FILE``, or ``/run/secrets/nccm_secrets_key`` if present

Device passwords never belong in ``.env`` — only this master key (or a mounted secret file).
"""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_ENV_KEY = "NCCM_SECRETS_KEY"
_ENV_KEY_FILE = "NCCM_SECRETS_KEY_FILE"
_DEFAULT_KEY_FILE = Path("/run/secrets/nccm_secrets_key")


class SecretsNotConfiguredError(RuntimeError):
    """Raised when encryption is required but no master key is available."""


class SecretsDecryptError(ValueError):
    """Raised when ciphertext cannot be decrypted with the current master key."""


def _read_key_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def get_master_key() -> bytes | None:
    """Return the Fernet master key bytes, or None if not configured."""
    raw = os.environ.get(_ENV_KEY, "").strip()
    if not raw:
        key_file = os.environ.get(_ENV_KEY_FILE, "").strip()
        path = Path(key_file) if key_file else _DEFAULT_KEY_FILE
        if path.is_file():
            raw = _read_key_file(path)
    if not raw:
        return None
    try:
        return raw.encode("ascii")
    except UnicodeEncodeError:
        return None


def secrets_configured() -> bool:
    return get_master_key() is not None


def _fernet() -> Fernet:
    key = get_master_key()
    if not key:
        raise SecretsNotConfiguredError(
            "NCCM_SECRETS_KEY is not set (env or secret file). "
            "Live schedules require a master encryption key."
        )
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a non-empty string; empty input returns empty string."""
    text = plaintext or ""
    if not text:
        return ""
    token = _fernet().encrypt(text.encode("utf-8"))
    return token.decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt Fernet token; empty input returns empty string."""
    blob = (ciphertext or "").strip()
    if not blob:
        return ""
    try:
        plain = _fernet().decrypt(blob.encode("ascii"))
    except InvalidToken as exc:
        raise SecretsDecryptError("credential decrypt failed") from exc
    return plain.decode("utf-8")
