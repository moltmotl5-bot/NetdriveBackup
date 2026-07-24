from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet


@pytest.fixture()
def secrets_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NCCM_SECRETS_KEY", key)
    monkeypatch.delenv("NCCM_SECRETS_KEY_FILE", raising=False)
    import importlib
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
    yield secrets
    importlib.reload(secrets)


@pytest.fixture()
def secrets_store_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("NCCM_STORE_DIR", str(store))
    monkeypatch.delenv("NCCM_SECRETS_KEY", raising=False)
    monkeypatch.delenv("NCCM_SECRETS_KEY_FILE", raising=False)
    import importlib
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
    yield secrets
    importlib.reload(secrets)


def test_secrets_not_configured_without_key(secrets_store_only):
    secrets = secrets_store_only
    assert secrets.secrets_configured() is False
    with pytest.raises(secrets.SecretsNotConfiguredError):
        secrets.encrypt("x")


def test_encrypt_decrypt_roundtrip(secrets_env):
    secrets = secrets_env
    plain = "ssh-secret-123"
    token = secrets.encrypt(plain)
    assert token
    assert token != plain
    assert secrets.decrypt(token) == plain


def test_encrypt_empty_returns_empty(secrets_env):
    secrets = secrets_env
    assert secrets.encrypt("") == ""
    assert secrets.decrypt("") == ""


def test_decrypt_invalid_token(secrets_env):
    secrets = secrets_env
    with pytest.raises(secrets.SecretsDecryptError):
        secrets.decrypt("not-a-valid-token")


def test_master_key_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key = Fernet.generate_key().decode()
    key_file = tmp_path / "nccm.key"
    key_file.write_text(key + "\n", encoding="utf-8")
    monkeypatch.delenv("NCCM_SECRETS_KEY", raising=False)
    monkeypatch.setenv("NCCM_SECRETS_KEY_FILE", str(key_file))
    import importlib
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
    assert secrets.secrets_configured() is True
    assert secrets.secrets_key_source() == "file"
    token = secrets.encrypt("from-file")
    assert secrets.decrypt(token) == "from-file"


def test_ensure_master_key_creates_store_file(secrets_store_only):
    secrets = secrets_store_only
    assert secrets.secrets_configured() is False
    result = secrets.ensure_master_key()
    assert result.created is True
    assert result.source == "store"
    assert secrets.secrets_configured() is True
    assert secrets.store_master_key_path().is_file()
    assert secrets.secrets_key_source() == "store"

    again = secrets.ensure_master_key()
    assert again.created is False
    assert again.source == "store"


def test_ensure_master_key_roundtrip_after_store_init(secrets_store_only):
    secrets = secrets_store_only
    secrets.ensure_master_key()
    token = secrets.encrypt("stored")
    assert secrets.decrypt(token) == "stored"
