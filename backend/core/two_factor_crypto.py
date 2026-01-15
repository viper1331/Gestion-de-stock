"""Utilitaires de chiffrement pour les secrets 2FA."""
from __future__ import annotations

import base64
import logging
import os
import threading
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Optional[Fernet] = None
_warned_insecure = False
_ready_logged = False
_fernet_lock = threading.Lock()


def _load_fernet_key() -> bytes:
    key = os.environ.get("TWO_FACTOR_ENCRYPTION_KEY")
    allow_insecure = os.environ.get("ALLOW_INSECURE_2FA_DEV") == "1"
    if not key:
        if allow_insecure:
            global _warned_insecure
            if not _warned_insecure:
                logger.warning(
                    "Clé TWO_FACTOR_ENCRYPTION_KEY absente; utilisation d'une clé 2FA éphémère (dev only)."
                )
                _warned_insecure = True
            return Fernet.generate_key()
        raise RuntimeError(
            "TWO_FACTOR_ENCRYPTION_KEY manquante (définissez ALLOW_INSECURE_2FA_DEV=1 pour un mode dev)."
        )
    try:
        decoded = base64.urlsafe_b64decode(key)
    except Exception as exc:  # pragma: no cover - validation explicite
        raise RuntimeError("TWO_FACTOR_ENCRYPTION_KEY invalide (base64).") from exc
    if len(decoded) != 32:
        raise RuntimeError("TWO_FACTOR_ENCRYPTION_KEY invalide (32 octets attendus).")
    return key.encode("utf-8")


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        with _fernet_lock:
            if _fernet is None:
                _fernet = Fernet(_load_fernet_key())
    return _fernet


def ensure_configured() -> None:
    """Vérifie la présence de la clé de chiffrement 2FA (fail fast en prod)."""
    global _ready_logged
    _get_fernet()
    if not _ready_logged:
        logger.info("2FA encryption ready")
        _ready_logged = True


def encrypt_secret(plain: str) -> str:
    """Chiffre un secret TOTP en base64."""

    token = _get_fernet().encrypt(plain.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(enc: str) -> str:
    """Déchiffre un secret TOTP depuis la base."""

    token = _get_fernet().decrypt(enc.encode("utf-8"))
    return token.decode("utf-8")
