from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import Settings, get_settings
from app.services.images import store_scraped_image

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 502, 503, 504}
_SCENE_FIELDS = """
    title code details date duration remote_site_id urls
    image studio { name } tags { name }
    performers { name remote_site_id urls image images }
"""
_SCENE_QUERY = """
query TVScrapeScene($source: ScraperSourceInput!, $input: ScrapeSingleSceneInput!) {
  scrapeSingleScene(source: $source, input: $input) { %s }
}
""" % _SCENE_FIELDS
_URL_QUERY = """
query TVScrapeSceneURL($url: String!) {
  scrapeSceneURL(url: $url) { %s }
}
""" % _SCENE_FIELDS


class StashError(Exception):
    pass


def graphql_url(raw: str) -> str:
    try:
        parts = urlsplit((raw or "").strip())
        _ = parts.port
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    path = parts.path.rstrip("/")
    if not path.endswith("/graphql"):
        path += "/graphql"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _http_url(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(("http://", "https://")):
            return value
    return None


def _urls(data: dict[str, Any]) -> list[str]:
    urls = data.get("urls")
    return [u for v in urls if (u := _http_url(v))] if isinstance(urls, list) else []


def _image(data: dict[str, Any]) -> str | None:
    images = data.get("images")
    candidates = images if isinstance(images, list) else []
    for value in [*candidates, data.get("image")]:
        if isinstance(value, str) and value.startswith(("http://", "https://", "data:image/")):
            return value
    return None


def _identity(value: str) -> str:
    return value if len(value) <= 128 else hashlib.sha256(value.encode()).hexdigest()


def _provider_key(scraper_id: str) -> str:
    value = f"stash:{scraper_id}"
    return value if len(value) <= 64 else f"stash:{hashlib.sha256(scraper_id.encode()).hexdigest()[:40]}"


def _matches_number(scene: dict[str, Any], query: str) -> bool:
    number = re.sub(r"[^a-z0-9]", "", query.lower())
    code = re.sub(r"[^a-z0-9]", "", str(scene.get("number") or "").lower())
    if not number:
        return False
    if code:
        return code == number
    tokens = re.findall(r"[a-z]+|[0-9]+", query.lower())
    pattern = r"(?<![a-z0-9])" + r"[-_\s]*".join(map(re.escape, tokens)) + r"(?![a-z0-9])"
    return any(re.search(pattern, str(value).lower()) for value in [scene.get("title"), *scene.get("_urls", [])] if value)


class StashClient:
    """Adapt Stash scene scrapers to the metadata shape consumed by TV."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.endpoint = graphql_url(self.settings.stash_base_url)
        self.token = self.settings.stash_api_key.strip()
        self._scrapers: list[dict[str, Any]] | None = None
        self._movies: dict[tuple[str, str], dict[str, Any]] = {}
        self._actors: dict[tuple[str, str], dict[str, Any]] = {}
        self._attempted: dict[str, set[str]] = {}

    async def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.endpoint:
            raise StashError("Configure a valid Stash HTTP(S) URL first")
        headers = {"Accept": "application/json", "User-Agent": "TV-App"}
        if self.token:
            headers["ApiKey"] = self.token
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                    response = await client.post(
                        self.endpoint, headers=headers,
                        json={"query": query, "variables": variables or {}},
                    )
            except (httpx.HTTPError, httpx.InvalidURL) as exc:
                if attempt < 3:
                    await asyncio.sleep(0.8 * attempt)
                    continue
                raise StashError(f"Stash request failed ({type(exc).__name__})") from exc
            if response.status_code in _RETRYABLE_STATUS and attempt < 3:
                await asyncio.sleep(0.8 * attempt)
                continue
            if not response.is_success:
                raise StashError(f"Stash HTTP {response.status_code}; check the URL, API key and service")
            try:
                body = response.json()
            except ValueError as exc:
                raise StashError("Stash returned invalid JSON; check the /graphql endpoint") from exc
            if not isinstance(body, dict):
                raise StashError("Invalid Stash GraphQL response")
            if body.get("errors"):
                errors = body["errors"]
                message = "; ".join(
                    str(e.get("message") or "GraphQL error")
                    for e in errors if isinstance(e, dict)
                ) if isinstance(errors, list) else "GraphQL error"
                if self.token:
                    message = message.replace(self.token, "[redacted]")
                raise StashError(f"Stash: {message[:300]}")
            data = body.get("data")
            if not isinstance(data, dict):
                raise StashError("Stash GraphQL response has no data")
            return data
        raise StashError("Stash request failed")

    async def ping(self) -> dict[str, Any]:
        data = await self._query("query TVStashVersion { version { version } }")
        return data

    async def list_scrapers(self) -> list[dict[str, Any]]:
        if self._scrapers is not None:
            return self._scrapers
        data = await self._query("""
            query TVSceneScrapers {
              listScrapers(types: [SCENE]) {
                id name scene { supported_scrapes urls }
              }
            }
        """)
        rows = data.get("listScrapers")
        if not isinstance(rows, list):
            raise StashError("Stash returned an invalid scraper list")
        scrapers = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("id") or not isinstance(row.get("scene"), dict):
                continue
            scene = row["scene"]
            types = scene.get("supported_scrapes") or []
            if not isinstance(types, list) or not {"NAME", "FRAGMENT", "URL"}.intersection(types):
                continue
            scrapers.append({
                "id": str(row["id"]), "name": str(row.get("name") or row["id"]),
                "types": types, "urls": scene.get("urls") or [],
            })
        self._scrapers = scrapers
        return scrapers

    def _normalize_actor(self, data: dict[str, Any], provider: str) -> dict[str, Any]:
        urls = _urls(data)
        actor_id = _identity(str((urls[0] if urls else None) or data.get("remote_site_id") or data.get("name") or ""))
        actor = {
            "name": data.get("name"), "provider": provider, "id": actor_id,
            "image_url": _image(data),
        }
        self._actors[provider, actor_id] = actor
        return actor

    def _normalize_scene(self, data: Any, scraper_id: str, query: str) -> dict[str, Any] | None:
        if not isinstance(data, dict) or not any(data.get(k) for k in ("title", "code", "details", "urls")):
            return None
        provider = _provider_key(scraper_id)
        urls = _urls(data)
        movie_id = _identity(str(data.get("remote_site_id") or (urls[0] if urls else None) or data.get("code") or query))
        studio = data.get("studio")
        actors = data.get("performers") or []
        tags = data.get("tags") or []
        seconds = data.get("duration")
        scene = {
            "provider": provider, "id": movie_id, "number": data.get("code") or "",
            "title": data.get("title") or data.get("code"), "summary": data.get("details"),
            "release_date": data.get("date"), "cover_url": _image(data),
            "studio": studio.get("name") if isinstance(studio, dict) else None,
            "runtime": max(1, (seconds + 59) // 60) if isinstance(seconds, int) and seconds > 0 else None,
            "genres": [str(t["name"]) for t in tags if isinstance(t, dict) and t.get("name")],
            "actors": [self._normalize_actor(a, provider) for a in actors if isinstance(a, dict) and a.get("name")],
            "_urls": urls,
            "_scraper_id": scraper_id,
            "_search_query": query,
            "_remote_site_id": data.get("remote_site_id"),
        }
        self._movies[provider, movie_id] = scene
        return scene

    async def _scrape(self, scraper: dict[str, Any], query: str) -> list[dict[str, Any]]:
        # Prefer NAME: fragments that depend on a Stash-local filename cannot use TV files.
        if "NAME" in scraper["types"]:
            inputs = {"query": query}
        elif "FRAGMENT" in scraper["types"]:
            inputs = {"scene_input": {"title": query, "code": query}}
        else:
            return []
        data = await self._query(_SCENE_QUERY, {"source": {"scraper_id": scraper["id"]}, "input": inputs})
        rows = data.get("scrapeSingleScene")
        if not isinstance(rows, list):
            raise StashError("Stash returned invalid scene results")
        scenes = [scene for row in rows if (scene := self._normalize_scene(row, scraper["id"], query))]
        if "NAME" in scraper["types"]:
            # Never mark an unrelated name-search result as the requested catalog number.
            scenes = [scene for scene in scenes if _matches_number(scene, query)]
            for scene in scenes:
                scene["_needs_detail"] = bool(scene["_urls"])
        else:
            scenes = [scene for scene in scenes if not scene.get("number") or _matches_number(scene, query)]
        return scenes

    async def search_movie(self, q: str, provider: str = "", fallback: bool = True) -> list[dict[str, Any]]:
        scrapers = await self.list_scrapers()
        selected = [s for s in scrapers if s["id"] == provider or s["name"] == provider] if provider else []
        if provider and not selected and not fallback:
            raise StashError(f"Stash scraper is not installed: {provider}")
        attempted = self._attempted.setdefault(q, set())
        candidates = selected + [s for s in scrapers if s not in selected and s["id"] not in attempted] if fallback or not provider else selected
        for scraper in candidates:
            if not {"NAME", "FRAGMENT"}.intersection(scraper["types"]):
                continue
            attempted.add(scraper["id"])
            logger.info("Stash try scraper=%s query=%s", scraper["id"], q)
            try:
                results = await self._scrape(scraper, q)
                if results:
                    return results
            except StashError:
                if provider and not fallback:
                    raise
                logger.warning("Stash scraper %s failed; trying the next scraper", scraper["id"])
        return []

    async def scrape_url(self, url: str) -> list[dict[str, Any]]:
        if not _http_url(url):
            raise StashError("A Stash source URL must use HTTP(S)")
        # URL scraping is matched by Stash itself, including URL-only scrapers.
        data = await self._query(_URL_QUERY, {"url": url})
        scene = self._normalize_scene(data.get("scrapeSceneURL"), "url", url)
        return [scene] if scene else []

    async def get_movie(self, provider: str, movie_id: str, lazy: bool = True) -> dict[str, Any]:
        scene = self._movies.get((provider, movie_id))
        if not scene:
            raise StashError("Stash scene is no longer available; search again")
        # Stash name queries return selection fragments. Complete them with the
        # same scraper's sceneByQueryFragment before trying automatic URL scraping.
        if scene.get("_needs_detail"):
            detail = None
            fragment = {
                "title": scene.get("title"), "code": scene.get("number"),
                "urls": scene["_urls"], "remote_site_id": scene.get("_remote_site_id"),
            }
            try:
                data = await self._query(_SCENE_QUERY, {
                    "source": {"scraper_id": scene["_scraper_id"]},
                    "input": {"scene_input": {key: value for key, value in fragment.items() if value}},
                })
                rows = data.get("scrapeSingleScene")
                if isinstance(rows, list):
                    for row in rows:
                        candidate = self._normalize_scene(row, scene["_scraper_id"], scene["_search_query"])
                        if candidate and (not candidate.get("number") or _matches_number(candidate, scene["_search_query"])):
                            detail = candidate
                            break
            except StashError:
                pass
            if detail is None:
                try:
                    data = await self._query(_URL_QUERY, {"url": scene["_urls"][0]})
                    candidate = self._normalize_scene(data.get("scrapeSceneURL"), scene["_scraper_id"], scene["_search_query"])
                    if candidate and (not candidate.get("number") or _matches_number(candidate, scene["_search_query"])):
                        detail = candidate
                except StashError:
                    pass
            if detail:
                # Preserve the identity selected by search even when detail has extra IDs.
                detail["id"] = movie_id
                scene = detail
            else:
                logger.warning("Could not expand a Stash search result; keeping available metadata")
        scene["cover_url"] = store_scraped_image(scene.get("cover_url"))
        for actor in scene["actors"]:
            actor["image_url"] = store_scraped_image(actor.get("image_url"))
        self._movies[provider, movie_id] = scene
        return scene

    async def get_actor(self, provider: str, actor_id: str) -> dict[str, Any]:
        actor = self._actors.get((provider, actor_id)) or {}
        if not actor.get("image_url") and _http_url(actor_id):
            data = await self._query("""
                query TVPerformerURL($url: String!) {
                  scrapePerformerURL(url: $url) { name remote_site_id urls image images }
                }
            """, {"url": actor_id})
            raw = data.get("scrapePerformerURL")
            if isinstance(raw, dict):
                actor = self._normalize_actor(raw, provider)
        actor["image_url"] = store_scraped_image(actor.get("image_url"))
        return actor
