"""Fonctions de sécurité (hashage et JWT)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt

ALGORITHM = "HS256"
SECRET_KEY = "change-me-please"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """Hash un mot de passe en utilisant bcrypt."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password, salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Vérifie qu'un mot de passe correspond à son hash."""
    if isinstance(password, str):
        password = password.encode("utf-8")
    if isinstance(hashed, str):
        hashed = hashed.encode("utf-8")
    return bcrypt.checkpw(password, hashed)


def _create_token(data: dict[str, Any], expires_delta: timedelta) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(subject: str, extra: Optional[dict[str, Any]] = None) -> str:
    payload = {"sub": subject}
    if extra:
        payload.update(extra)
    return _create_token(payload, timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(subject: str, extra: Optional[dict[str, Any]] = None) -> str:
    payload = {"sub": subject, "type": "refresh"}
    if extra:
        payload.update(extra)
    return _create_token(payload, timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict[str, Any]:
    """Decode un JWT et renvoie sa charge utile."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
