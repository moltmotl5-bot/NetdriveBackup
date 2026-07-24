from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet


@pytest.fixture()
def secrets_env(monkeypatch: pytest.MonkeyPatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NCCM_SECRETS_KEY", key)
    monkeypatch.delenv("NCCM_SECRETS_KEY_FILE", raising=False)
    import importlib
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
    yield secrets
    importlib.reload(secrets)


def test_secrets_not_configured_without_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("NCCM_SECRETS_KEY", raising=False)
    monkeypatch.delenv("NCCM_SECRETS_KEY_FILE", raising=False)
    import importlib
    import nccm.backup.secrets as secrets

    importlib.reload(secrets)
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
    token = secrets.encrypt("from-file")
    assert secrets.decrypt(token) == "from-file"
