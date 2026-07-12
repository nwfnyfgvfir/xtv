from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings


class AlistError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AlistClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base = self.settings.alist_base_url.rstrip("/")
        self.token = self.settings.alist_token.strip()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = self.token
        return h

    async def fs_get(self, path: str, password: str = "") -> dict[str, Any]:
        url = f"{self.base}/api/fs/get"
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(
                url,
                json={"path": path, "password": password},
                headers=self._headers(),
            )
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise AlistError(f"Invalid JSON from Alist ({resp.status_code})", resp.status_code) from exc
        if body.get("code") not in (200, None) and body.get("code") != 200:
            # Alist uses code 200 for success
            if isinstance(body.get("code"), int) and body["code"] != 200:
                raise AlistError(body.get("message") or f"Alist error {body.get('code')}", body.get("code"))
        if not resp.is_success:
            raise AlistError(body.get("message") or resp.text, resp.status_code)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise AlistError("Alist response missing data")
        return data

    async def raw_url(self, path: str) -> str:
        data = await self.fs_get(path)
        raw = data.get("raw_url") or data.get("raw_url".upper())
        if not raw:
            # some versions nest differently
            raw = data.get("sign") and data.get("name")  # fallback unused
        if not raw:
            raise AlistError(f"No raw_url for path: {path}")
        return str(raw)
