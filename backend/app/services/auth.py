from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings


def verify_password(password: str) -> bool:
    settings = get_settings()
    expected = settings.admin_password
    if not expected:
        return False
    return secrets.compare_digest(password, expected)


def create_access_token() -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
