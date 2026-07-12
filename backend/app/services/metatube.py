from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 502, 503, 504}
_MAX_ATTEMPTS = 3


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
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    resp = await client.get(url, params=params, headers=self._headers(auth=auth))
            except httpx.HTTPError as exc:
                last_exc = MetaTubeError(f"MetaTube request failed: {exc}")
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.8 * attempt)
                    continue
                raise last_exc from exc

            try:
                body = resp.json()
            except Exception as exc:  # noqa: BLE001
                snippet = (resp.text or "")[:200]
                logger.debug("MetaTube non-JSON body status=%s: %s", resp.status_code, snippet)
                last_exc = MetaTubeError(
                    f"Invalid JSON from MetaTube ({resp.status_code})",
                    resp.status_code,
                )
                if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(0.8 * attempt)
                    continue
                raise last_exc from exc

            if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(0.8 * attempt)
                continue

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

        if last_exc:
            raise last_exc
        raise MetaTubeError("MetaTube request failed")

    async def ping(self) -> dict[str, Any]:
        data = await self._get("/", auth=False)
        return data if isinstance(data, dict) else {"raw": data}

    async def search_movie(self, q: str, provider: str = "", fallback: bool = True) -> list[dict[str, Any]]:
        data = await self._get(
            "/v1/movies/search",
            params={"q": q, "provider": provider or "", "fallback": str(fallback).lower()},
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

    async def list_providers(self) -> dict[str, Any]:
        data = await self._get("/v1/providers", auth=True)
        return data if isinstance(data, dict) else {}

    async def search_actor(self, q: str, provider: str = "") -> list[dict[str, Any]]:
        data = await self._get(
            "/v1/actors/search",
            params={"q": q, "provider": provider or ""},
            auth=True,
        )
        return data if isinstance(data, list) else []

    async def get_actor(self, provider: str, actor_id: str) -> dict[str, Any]:
        data = await self._get(f"/v1/actors/{provider}/{actor_id}", auth=True)
        return data if isinstance(data, dict) else {}

    def primary_image_url(self, provider: str, movie_id: str, url: str = "", quality: int = 90) -> str:
        from urllib.parse import quote, urlencode

        qs = urlencode({"url": url, "quality": quality}) if url else urlencode({"quality": quality})
        path = f"{self.base}/v1/images/primary/{quote(provider, safe='')}/{quote(movie_id, safe='')}"
        return f"{path}?{qs}" if qs else path

    def proxied_image_url(self, provider: str | None, provider_id: str | None, url: str | None) -> str | None:
        """Rewrite image URL using current IMAGE_PROXY_MODE."""
        from app.services.images import rewrite_image_url

        return rewrite_image_url(url, provider=provider, provider_id=provider_id)
