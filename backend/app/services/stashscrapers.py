from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, get_settings
from app.services.images import store_scraped_image


class StashScrapersError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def service_url(raw: str) -> str:
    try:
        parts = urlsplit((raw or "").strip())
        _ = parts.port
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        if parts.username or parts.password or parts.query or parts.fragment:
            return ""
    except ValueError:
        return ""
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[:-4]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _urls(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [v.strip() for v in values if isinstance(v, str) and v.strip().startswith(("http://", "https://"))]


def _identity(value: str, limit: int = 128) -> str:
    return value if len(value) <= limit else hashlib.sha256(value.encode()).hexdigest()


def _provider(scraper_id: str) -> str:
    value = "stashscrapers:" + scraper_id
    return value if len(value) <= 64 else "stashscrapers:" + hashlib.sha256(scraper_id.encode()).hexdigest()[:48]


def _matches_url(url: str, pattern: Any) -> bool:
    if not isinstance(pattern, str) or not pattern or pattern not in url:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower()
        expected = (urlsplit(pattern if "://" in pattern else "https://" + pattern).hostname or "").lower()
    except ValueError:
        return False
    return bool(expected) and (host == expected or host.endswith("." + expected))


def _matches(scene: dict[str, Any], query: str) -> bool:
    expected = re.sub(r"[^a-z0-9]", "", query.lower())
    code = re.sub(r"[^a-z0-9]", "", str(scene.get("code") or "").lower())
    if not expected:
        return False
    if code:
        return code == expected
    tokens = re.findall(r"[a-z]+|[0-9]+", query.lower())
    pattern = r"(?<![a-z0-9])" + r"[-_\s]*".join(map(re.escape, tokens)) + r"(?![a-z0-9])"
    return any(re.search(pattern, str(v).lower()) for v in [scene.get("title"), *_urls(scene.get("urls"))] if v)


class StashScrapersClient:
    """REST adapter for the standalone stashscrapers service, not Stash GraphQL."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base = service_url(self.settings.stashscrapers_base_url)
        self.token = self.settings.stashscrapers_token.strip()
        self._catalog: list[dict[str, Any]] | None = None
        self._movies: dict[tuple[str, str], dict[str, Any]] = {}
        self._actors: dict[tuple[str, str], dict[str, Any]] = {}

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base:
            raise StashScrapersError("Configure a valid StashScrapers HTTP(S) service address first")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(65.0, connect=10.0)) as client:
                response = await client.request(method, self.base + "/api/" + path, headers=headers, json=body)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise StashScrapersError(f"StashScrapers request failed ({type(exc).__name__})") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise StashScrapersError(f"StashScrapers returned invalid JSON (HTTP {response.status_code})") from exc
        if not isinstance(data, dict):
            raise StashScrapersError("Invalid StashScrapers response")
        error = data.get("error")
        if not response.is_success or error:
            code = str(error.get("code") or "") if isinstance(error, dict) else ""
            message = str(error.get("message") or "") if isinstance(error, dict) else ""
            if self.token:
                message = message.replace(self.token, "[redacted]")
                code = code.replace(self.token, "[redacted]")
            raise StashScrapersError(f"StashScrapers HTTP {response.status_code} [{code or 'error'}]: {message[:240]}", code)
        return data

    async def _entries(self) -> list[dict[str, Any]]:
        if self._catalog is None:
            data = await self._request("GET", "scrapers")
            if not isinstance(data.get("scrapers"), list):
                raise StashScrapersError("StashScrapers returned an invalid scraper catalog")
            self._catalog = [row for row in data["scrapers"] if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]]
        return self._catalog

    @staticmethod
    def _operations(entry: dict[str, Any], kind: str = "scene") -> list[dict[str, Any]]:
        if entry.get("enabled") is not True:
            return []
        operations = entry.get("operations")
        return [op for op in operations if isinstance(op, dict) and op.get("object") == kind and op.get("state") == "available"] if isinstance(operations, list) else []

    async def list_scrapers(self) -> list[dict[str, Any]]:
        rows = []
        for entry in await self._entries():
            operations = {op.get("operation") for op in self._operations(entry)}
            types = [name for op, name in (("name", "NAME"), ("fragment", "FRAGMENT"), ("url", "URL")) if op in operations]
            if types:
                rows.append({"id": entry["id"], "name": str(entry.get("name") or entry["id"]), "types": types})
        return rows

    async def ping(self) -> dict[str, Any]:
        data = await self._request("GET", "health")
        if data.get("status") != "ok" or data.get("ready") is not True:
            raise StashScrapersError("StashScrapers is running but its scraper resources are not ready")
        # Health is public; the catalog also verifies the configured Bearer token.
        data["available_scene_scrapers"] = len(await self.list_scrapers())
        return data

    async def _results(self, path: str, body: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        try:
            data = await self._request("POST", path, body)
        except StashScrapersError as exc:
            if exc.code == "not_found":
                return [], ""
            raise
        if not isinstance(data.get("results"), list):
            raise StashScrapersError("StashScrapers returned invalid scrape results")
        version = data.get("rules_version")
        if not isinstance(version, str) or not version:
            raise StashScrapersError("StashScrapers did not identify its active rules version")
        if body.get("rules_version") and version != body["rules_version"]:
            raise StashScrapersError("StashScrapers changed rules during scraping", "version_conflict")
        return [row for row in data["results"] if isinstance(row, dict)], version

    def _normalize(self, result: dict[str, Any], scraper_id: str, query: str) -> dict[str, Any]:
        provider = _provider(scraper_id)
        urls = _urls(result.get("urls"))
        movie_id = _identity(str((urls[0] if urls else None) or result.get("code") or query))
        raw = result.get("raw") if isinstance(result.get("raw"), dict) else {}
        images = result.get("images") or raw.get("images") or [raw.get("image")]
        cover = next((store_scraped_image(v) for v in images if isinstance(v, str) and v), None) if isinstance(images, list) else None
        actors = []
        for person in result.get("performers") or []:
            if not isinstance(person, dict) or not person.get("name"):
                continue
            person_urls = _urls(person.get("urls") or person.get("url"))
            actor_id = _identity(str((person_urls[0] if person_urls else None) or person["name"]))
            portraits = person.get("images") or [person.get("image")]
            portrait = next((store_scraped_image(v) for v in portraits if isinstance(v, str) and v), None) if isinstance(portraits, list) else None
            actor = {"name": person["name"], "provider": provider, "id": actor_id, "image_url": portrait}
            self._actors[provider, actor_id] = actor
            actors.append(actor)
        studio = result.get("studio")
        duration = result.get("duration")
        tags = result.get("tags") or []
        scene = {
            "provider": provider, "id": movie_id, "number": result.get("code") or "",
            "title": result.get("title"), "summary": result.get("details"),
            "release_date": result.get("date"), "cover_url": cover,
            "studio": studio.get("name") if isinstance(studio, dict) else studio,
            "runtime": max(1, (duration + 59) // 60) if isinstance(duration, int) and not isinstance(duration, bool) and duration > 0 else None,
            "genres": [str(tag.get("name")) if isinstance(tag, dict) else tag for tag in tags if isinstance(tag, str) or isinstance(tag, dict) and tag.get("name")],
            "actors": actors,
        }
        self._movies[provider, movie_id] = scene
        return scene

    async def _number(self, entry: dict[str, Any], query: str) -> list[dict[str, Any]]:
        operations = {op.get("operation") for op in self._operations(entry)}
        scraper_id = entry["id"]
        if "name" in operations:
            results, version = await self._results("search", {"scraper_id": scraper_id, "object": "scene", "query": query})
            for result in results:
                if not _matches(result, query):
                    continue
                body: dict[str, Any] = {"scraper_id": scraper_id, "object": "scene", "rules_version": version}
                if "query_fragment" in operations and isinstance(result.get("raw"), dict) and result["raw"]:
                    body.update(operation="query_fragment", fragment=result["raw"])
                elif "url" in operations and _urls(result.get("urls")):
                    body["url"] = _urls(result["urls"])[0]
                else:
                    return [self._normalize(result, scraper_id, query)]
                details, _ = await self._results("detail", body)
                for detail in details:
                    if not detail.get("code") or _matches(detail, query):
                        return [self._normalize(detail, scraper_id, query)]
        if "fragment" in operations:
            results, _ = await self._results("detail", {
                "scraper_id": scraper_id, "object": "scene", "operation": "fragment",
                "fragment": {"filename": query, "title": query, "code": query},
                "rules_version": entry.get("version") or "",
            })
            return [self._normalize(row, scraper_id, query) for row in results if _matches(row, query)]
        return []

    async def _run(self, query: str, provider: str, fallback: bool, *, by_url: bool = False) -> list[dict[str, Any]]:
        for attempt in range(2):
            try:
                entries = await self._entries()
                usable = []
                for row in entries:
                    operations = self._operations(row)
                    if by_url:
                        if not any(op.get("operation") == "url" and any(_matches_url(query, pattern) for pattern in op.get("urls", [])) for op in operations):
                            continue
                    elif not any(op.get("operation") in {"name", "fragment"} for op in operations):
                        continue
                    usable.append(row)
                selected = [row for row in usable if provider in {row["id"], row.get("name")}] if provider else []
                if provider and not selected and not fallback:
                    raise StashScrapersError("The selected StashScrapers scraper is unavailable for this operation")
                candidates = selected + [row for row in usable if row not in selected] if fallback or not provider else selected
                last_error: StashScrapersError | None = None
                for entry in candidates:
                    try:
                        if by_url:
                            results, _ = await self._results("detail", {"scraper_id": entry["id"], "object": "scene", "url": query, "rules_version": entry.get("version") or ""})
                            scenes = [self._normalize(row, entry["id"], query) for row in results]
                        else:
                            scenes = await self._number(entry, query)
                        if scenes:
                            return scenes
                    except StashScrapersError as exc:
                        if exc.code == "version_conflict" or not fallback and provider:
                            raise
                        last_error = exc
                if last_error:
                    raise last_error
                return []
            except StashScrapersError as exc:
                if exc.code != "version_conflict" or attempt:
                    raise
                self._catalog = None
        return []

    async def search_movie(self, q: str, provider: str = "", fallback: bool = True) -> list[dict[str, Any]]:
        return await self._run(q, provider, fallback)

    async def scrape_url(self, url: str, provider: str = "", fallback: bool = True) -> list[dict[str, Any]]:
        if not _urls(url):
            raise StashScrapersError("A source URL must use HTTP(S)")
        return await self._run(url, provider, fallback, by_url=True)

    async def get_movie(self, provider: str, movie_id: str, lazy: bool = True) -> dict[str, Any]:
        scene = self._movies.get((provider, movie_id))
        if scene is None:
            raise StashScrapersError("StashScrapers scene is no longer available; search again")
        return scene

    async def get_actor(self, provider: str, actor_id: str) -> dict[str, Any]:
        actor = self._actors.get((provider, actor_id))
        if actor and actor.get("image_url"):
            return actor
        if _urls(actor_id):
            for entry in await self._entries():
                if _provider(entry["id"]) != provider:
                    continue
                if not any(op.get("operation") == "url" and any(_matches_url(actor_id, pattern) for pattern in op.get("urls", [])) for op in self._operations(entry, "performer")):
                    continue
                results, _ = await self._results("detail", {"scraper_id": entry["id"], "object": "performer", "url": actor_id, "rules_version": entry.get("version") or ""})
                if results:
                    result = results[0]
                    images = result.get("images") or []
                    image = next((store_scraped_image(v) for v in images if isinstance(v, str) and v), None)
                    return {"name": result.get("name"), "provider": provider, "id": actor_id, "image_url": image}
        return actor or {}
