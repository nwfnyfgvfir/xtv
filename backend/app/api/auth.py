from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.deps import optional_auth, require_auth
from app.schemas import AuthStatusOut, LoginIn, LoginOut
from app.services.auth import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusOut)
def auth_status(user: Annotated[dict | None, Depends(optional_auth)]) -> AuthStatusOut:
    settings = get_settings()
    return AuthStatusOut(
        auth_enabled=settings.auth_enabled,
        authenticated=bool(user) and not user.get("auth_disabled"),
    )


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn) -> LoginOut:
    settings = get_settings()
    if not settings.auth_enabled:
        # Dev mode: still return a token so clients can store one
        return LoginOut(access_token=create_access_token(), auth_enabled=False)
    if not verify_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password")
    return LoginOut(access_token=create_access_token(), auth_enabled=True)


@router.get("/me")
def me(user: Annotated[dict, Depends(require_auth)]) -> dict:
    return {"user": user.get("sub", "admin"), "auth_enabled": get_settings().auth_enabled}
