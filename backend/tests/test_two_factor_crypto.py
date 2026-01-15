from __future__ import annotations

import base64

import pytest

from backend.core import two_factor_crypto


def _reset_crypto_state() -> None:
    two_factor_crypto._fernet = None
    two_factor_crypto._warned_insecure = False
    two_factor_crypto._ready_logged = False


def _valid_key() -> str:
    return base64.urlsafe_b64encode(b"1" * 32).decode("utf-8")


def test_startup_with_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWO_FACTOR_ENCRYPTION_KEY", _valid_key())
    monkeypatch.delenv("ALLOW_INSECURE_2FA_DEV", raising=False)
    _reset_crypto_state()
    two_factor_crypto.ensure_configured()


def test_encrypt_decrypt_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWO_FACTOR_ENCRYPTION_KEY", _valid_key())
    monkeypatch.delenv("ALLOW_INSECURE_2FA_DEV", raising=False)
    _reset_crypto_state()
    plain = "totp-secret-123"
    encrypted = two_factor_crypto.encrypt_secret(plain)
    assert encrypted != plain
    assert two_factor_crypto.decrypt_secret(encrypted) == plain


def test_dev_fallback_allowed_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWO_FACTOR_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_2FA_DEV", "1")
    _reset_crypto_state()
    two_factor_crypto.ensure_configured()
    assert two_factor_crypto.decrypt_secret(two_factor_crypto.encrypt_secret("dev")) == "dev"


def test_missing_key_in_prod_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWO_FACTOR_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_2FA_DEV", raising=False)
    _reset_crypto_state()
    with pytest.raises(RuntimeError):
        two_factor_crypto.ensure_configured()


def test_invalid_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWO_FACTOR_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"short").decode("utf-8"))
    monkeypatch.delenv("ALLOW_INSECURE_2FA_DEV", raising=False)
    _reset_crypto_state()
    with pytest.raises(RuntimeError):
        two_factor_crypto.ensure_configured()
