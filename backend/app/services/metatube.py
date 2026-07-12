from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings


class MetaTubeError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class MetaTubeClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base = self.settings.metatube_base_url.rstrip("/")
        self.token = self.settings.metatube_token.strip()

    def _headers(self, auth: bool = True) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "User-Agent": "TV-App/0.1",
        }
        if auth and self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _get(self, path: str, params: dict[str, Any] | None = None, auth: bool = True) -> Any:
        url = f"{self.base}{path}"
        timeout = httpx.Timeout(60.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, params=params, headers=self._headers(auth=auth))
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise MetaTubeError(f"Invalid JSON from MetaTube ({resp.status_code})", resp.status_code) from exc
        if not resp.is_success:
            err = body.get("error") if isinstance(body, dict) else None
            msg = err.get("message") if isinstance(err, dict) else resp.text
            raise MetaTubeError(msg or f"HTTP {resp.status_code}", resp.status_code)
        if isinstance(body, dict) and "error" in body and body["error"]:
            err = body["error"]
            raise MetaTubeError(err.get("message", "MetaTube error"), err.get("code"))
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    async def ping(self) -> dict[str, Any]:
        data = await self._get("/", auth=False)
        return data if isinstance(data, dict) else {"raw": data}

    async def search_movie(self, q: str, provider: str = "", fallback: bool = True) -> list[dict[str, Any]]:
        data = await self._get(
            "/v1/movies/search",
            params={"q": q, "provider": provider, "fallback": str(fallback).lower()},
            auth=True,
        )
        return data if isinstance(data, list) else []

    async def get_movie(self, provider: str, movie_id: str, lazy: bool = True) -> dict[str, Any]:
        data = await self._get(
            f"/v1/movies/{provider}/{movie_id}",
            params={"lazy": str(lazy).lower()},
            auth=True,
        )
        return data if isinstance(data, dict) else {}

    def primary_image_url(self, provider: str, movie_id: str, url: str = "", quality: int = 90) -> str:
        from urllib.parse import quote, urlencode

        qs = urlencode({"url": url, "quality": quality})
        return f"{self.base}/v1/images/primary/{quote(provider, safe='')}/{quote(movie_id, safe='')}" + (f"?{qs}" if qs else "")
