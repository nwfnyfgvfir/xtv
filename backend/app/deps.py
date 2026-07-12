from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.services.auth import decode_token

_bearer = HTTPBearer(auto_error=False)


def require_auth(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    """Require JWT when ADMIN_PASSWORD is configured; otherwise allow all."""
    settings = get_settings()
    if not settings.auth_enabled:
        return {"sub": "anonymous", "auth_disabled": True}
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    try:
        return decode_token(creds.credentials)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc


def optional_auth(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict | None:
    settings = get_settings()
    if not settings.auth_enabled:
        return {"sub": "anonymous", "auth_disabled": True}
    if creds is None or not creds.credentials:
        return None
    try:
        return decode_token(creds.credentials)
    except Exception:  # noqa: BLE001
        return None
