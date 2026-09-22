"""Password hashing and JWT helpers (Phase 3 §5).

Passwords are hashed with bcrypt (via passlib); refresh/password-reset
tokens are never stored raw -- only a SHA-256 hash of them -- so a database
leak alone doesn't hand out usable credentials.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_ACCESS_TOKEN_TYPE = "access"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": _ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises `jwt.PyJWTError` (or a subclass, e.g. `ExpiredSignatureError`)
    on an invalid/expired/wrong-type token -- callers translate that into a
    401 rather than handling each failure mode individually."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != _ACCESS_TOKEN_TYPE:
        raise jwt.InvalidTokenError("Not an access token")
    return payload


def hash_token(raw_token: str) -> str:
    """Deterministic hash used for refresh/password-reset tokens, so a
    lookup can find a row by hashing the presented raw token without ever
    storing the raw value."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_raw_token() -> str:
    return secrets.token_urlsafe(32)
