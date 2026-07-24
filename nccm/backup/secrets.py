"""Encrypt schedule SSH credentials at rest (Fernet).

Master key sources (first match wins):
  1. ``NCCM_SECRETS_KEY`` environment variable (urlsafe base64, 32 bytes)
  2. File path from ``NCCM_SECRETS_KEY_FILE``, or ``/run/secrets/nccm_secrets_key`` if present
  3. ``store/.secrets/fernet.key`` — auto-created on first live schedule credential (Phase A′)

Device SSH passwords never belong in ``.env``. The master key may live in env, a mounted
secret file, or the persisted store volume (created from the schedules UI).
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from nccm.config import store_dir

_ENV_KEY = "NCCM_SECRETS_KEY"
_ENV_KEY_FILE = "NCCM_SECRETS_KEY_FILE"
_DEFAULT_KEY_FILE = Path("/run/secrets/nccm_secrets_key")
_STORE_SECRETS_DIR = ".secrets"
_STORE_KEY_NAME = "fernet.key"


class SecretsNotConfiguredError(RuntimeError):
    """Raised when encryption is required but no master key is available."""


class SecretsDecryptError(ValueError):
    """Raised when ciphertext cannot be decrypted with the current master key."""


class SecretsKeyWriteError(OSError):
    """Raised when the auto-generated store key cannot be written."""


@dataclass(frozen=True)
class KeyEnsureResult:
    created: bool
    source: str


def store_master_key_path() -> Path:
    return store_dir() / _STORE_SECRETS_DIR / _STORE_KEY_NAME


def _read_key_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _env_master_key() -> bytes | None:
    raw = os.environ.get(_ENV_KEY, "").strip()
    if not raw:
        return None
    try:
        return raw.encode("ascii")
    except UnicodeEncodeError:
        return None


def _file_master_key(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    raw = _read_key_file(path)
    if not raw:
        return None
    try:
        return raw.encode("ascii")
    except UnicodeEncodeError:
        return None


def secrets_key_source() -> str | None:
    """Return how the master key is resolved: env, file, or store."""
    if _env_master_key() is not None:
        return "env"
    key_file = os.environ.get(_ENV_KEY_FILE, "").strip()
    path = Path(key_file) if key_file else _DEFAULT_KEY_FILE
    if _file_master_key(path) is not None:
        return "file"
    if _file_master_key(store_master_key_path()) is not None:
        return "store"
    return None


def get_master_key() -> bytes | None:
    """Return the Fernet master key bytes, or None if not configured."""
    env_key = _env_master_key()
    if env_key is not None:
        return env_key
    key_file = os.environ.get(_ENV_KEY_FILE, "").strip()
    path = Path(key_file) if key_file else _DEFAULT_KEY_FILE
    file_key = _file_master_key(path)
    if file_key is not None:
        return file_key
    return _file_master_key(store_master_key_path())


def secrets_configured() -> bool:
    return get_master_key() is not None


def _restrict_path_mode(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _write_store_master_key(raw: str) -> None:
    key_path = store_master_key_path()
    key_dir = key_path.parent
    key_dir.mkdir(parents=True, exist_ok=True)
    _restrict_path_mode(key_dir, stat.S_IRWXU)
    tmp_path = key_dir / f".{key_path.name}.tmp"
    try:
        tmp_path.write_text(raw + "\n", encoding="utf-8")
        _restrict_path_mode(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        tmp_path.replace(key_path)
        _restrict_path_mode(key_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise SecretsKeyWriteError(
            f"無法寫入加密金鑰至 {key_path}；請確認 store 目錄可寫"
        ) from exc


def ensure_master_key() -> KeyEnsureResult:
    """Ensure a master key exists; auto-create under store/ when allowed.

    Returns whether a new store key was created in this call.
    """
    existing = get_master_key()
    if existing is not None:
        src = secrets_key_source() or "unknown"
        return KeyEnsureResult(created=False, source=src)

    if _env_master_key() is not None or (
        _file_master_key(
            Path(os.environ.get(_ENV_KEY_FILE, "").strip())
            if os.environ.get(_ENV_KEY_FILE, "").strip()
            else _DEFAULT_KEY_FILE
        )
        is not None
    ):
        src = secrets_key_source() or "unknown"
        return KeyEnsureResult(created=False, source=src)

    key_path = store_master_key_path()
    if key_path.is_file():
        raw = _read_key_file(key_path)
        if raw:
            return KeyEnsureResult(created=False, source="store")

    lock_path = key_path.parent / "fernet.key.lock"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_path_mode(key_path.parent, stat.S_IRWXU)

    import fcntl

    with open(lock_path, "a+", encoding="utf-8") as lock_fp:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX)
        try:
            again = get_master_key()
            if again is not None:
                src = secrets_key_source() or "unknown"
                return KeyEnsureResult(created=False, source=src)
            if key_path.is_file():
                raw = _read_key_file(key_path)
                if raw:
                    return KeyEnsureResult(created=False, source="store")
            raw = Fernet.generate_key().decode("ascii")
            _write_store_master_key(raw)
            return KeyEnsureResult(created=True, source="store")
        finally:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)


def _fernet() -> Fernet:
    key = get_master_key()
    if not key:
        raise SecretsNotConfiguredError(
            "加密主金鑰尚未設定。建立 live 排程並輸入 SSH 密碼時會自動初始化，"
            "或設定 NCCM_SECRETS_KEY / secret 檔。"
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
