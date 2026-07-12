from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Actor, MediaItem
from app.services.metatube import MetaTubeClient, MetaTubeError

logger = logging.getLogger(__name__)


def _pick_best(results: list[dict[str, Any]], number: str) -> dict[str, Any] | None:
    if not results:
        return None
    n = number.upper().replace("_", "-")
    for r in results:
        rn = str(r.get("number") or "").upper().replace("_", "-")
        if rn == n:
            return r
    for r in results:
        rid = str(r.get("id") or "").upper().replace("_", "-")
        if rid == n or n in rid:
            return r
    return results[0]


def _first_image(v: Any) -> str | None:
    if isinstance(v, str) and v.startswith("http"):
        return v
    if isinstance(v, list):
        for x in v:
            if isinstance(x, str) and x.startswith("http"):
                return x
            if isinstance(x, dict):
                u = x.get("url") or x.get("thumb") or x.get("image")
                if isinstance(u, str) and u.startswith("http"):
                    return u
    return None


def _actor_list(detail: dict[str, Any]) -> list[dict[str, Any]]:
    actors = detail.get("actors") or detail.get("Actors") or []
    if not isinstance(actors, list):
        return []
    out: list[dict[str, Any]] = []
    for a in actors:
        if isinstance(a, str):
            out.append({"name": a})
        elif isinstance(a, dict):
            name = a.get("name") or a.get("Name")
            if name:
                img = _first_image(
                    a.get("image_url") or a.get("images") or a.get("thumb_url") or a.get("image")
                )
                out.append(
                    {
                        "name": name,
                        "provider": a.get("provider") or a.get("Provider"),
                        "provider_id": a.get("id") or a.get("ID") or a.get("provider_id"),
                        "image_url": img,
                    }
                )
    return out


async def scrape_media_item(
    db: Session,
    item: MediaItem,
    force: bool = False,
    provider_override: str | None = None,
    fallback_override: bool | None = None,
) -> bool:
    """Scrape metadata for a media item. Returns True if updated."""
    if not item.number:
        return False
    if item.scraped_at and not force:
        return False

    client = MetaTubeClient()
    if not client.token:
        logger.warning("MetaTube token empty; skip scrape for %s", item.number)
        return False

    try:
        settings = get_settings()
        provider_q = (
            provider_override
            if provider_override is not None
            else (settings.metatube_provider or "")
        )
        fallback = (
            fallback_override if fallback_override is not None else settings.metatube_fallback
        )
        results = await client.search_movie(
            item.number,
            provider=provider_q or "",
            fallback=fallback,
        )
        best = _pick_best(results, item.number)
        if not best:
            logger.info("No MetaTube result for %s", item.number)
            return False

        provider = str(best.get("provider") or "")
        provider_id = str(best.get("id") or "")
        detail: dict[str, Any] = {}
        if provider and provider_id:
            try:
                detail = await client.get_movie(provider, provider_id, lazy=True)
            except MetaTubeError as exc:
                logger.warning("get_movie failed %s/%s: %s", provider, provider_id, exc)
                detail = best
        else:
            detail = best

        item.title = detail.get("title") or best.get("title") or item.title
        item.plot = detail.get("summary") or detail.get("plot") or detail.get("description") or item.plot
        item.provider = provider or item.provider
        item.provider_id = provider_id or item.provider_id

        # Store ORIGINAL source URLs; API layer rewrites to site proxy.
        item.cover_url = detail.get("cover_url") or best.get("cover_url") or item.cover_url
        item.thumb_url = detail.get("thumb_url") or best.get("thumb_url") or item.thumb_url
        item.backdrop_url = (
            detail.get("big_cover_url") or detail.get("backdrop_url") or item.backdrop_url
        )

        item.score = _as_float(detail.get("score") if detail.get("score") is not None else best.get("score"))
        item.studio = _first_str(detail.get("maker") or detail.get("studio") or detail.get("label"))
        item.runtime = _as_int(detail.get("runtime") or detail.get("duration"))
        rd = detail.get("release_date") or best.get("release_date")
        if rd is not None:
            item.release_date = str(rd)[:32]

        genres = detail.get("genres") or detail.get("tags") or []
        if isinstance(genres, list) and genres:
            tags = [g if isinstance(g, str) else str(g.get("name", g)) for g in genres]
            if item.subtitle_flag == "C" and "中文字幕" not in tags:
                tags.append("中文字幕")
            item.tags_json = json.dumps(tags, ensure_ascii=False)
        elif item.subtitle_flag == "C":
            item.tags_json = json.dumps(["中文字幕"], ensure_ascii=False)

        item.actors.clear()
        for a in _actor_list(detail):
            actor = await _upsert_actor(db, client, a)
            if actor not in item.actors:
                item.actors.append(actor)

        item.scraped_at = datetime.now(timezone.utc)
        db.add(item)
        db.commit()
        db.refresh(item)
        return True
    except MetaTubeError as exc:
        logger.warning("scrape failed for %s: %s", item.number, exc)
        db.rollback()
        return False
    except Exception:  # noqa: BLE001
        logger.exception("unexpected scrape error for %s", item.number)
        db.rollback()
        return False


async def enrich_actor_image(db: Session, actor: Actor, client: MetaTubeClient | None = None) -> bool:
    """Fetch actor portrait from MetaTube Gfriends search if missing."""
    if actor.image_url:
        return False
    client = client or MetaTubeClient()
    if not client.token:
        return False
    try:
        results = await client.search_actor(actor.name)
        if not results:
            return False
        best = results[0]
        img = _first_image(best.get("images") or best.get("image_url") or best.get("image"))
        if not img:
            return False
        actor.image_url = img
        if not actor.provider:
            actor.provider = str(best.get("provider") or "Gfriends")
        if not actor.provider_id:
            actor.provider_id = str(best.get("id") or actor.name)
        db.add(actor)
        db.commit()
        return True
    except MetaTubeError as exc:
        logger.debug("actor image scrape failed %s: %s", actor.name, exc)
        return False
    except Exception:  # noqa: BLE001
        logger.debug("actor image scrape error %s", actor.name, exc_info=True)
        return False


async def _upsert_actor(db: Session, client: MetaTubeClient, data: dict[str, Any]) -> Actor:
    name = str(data["name"])
    provider = data.get("provider")
    provider_id = data.get("provider_id")
    actor: Actor | None = None
    if provider and provider_id:
        actor = (
            db.query(Actor)
            .filter(Actor.provider == provider, Actor.provider_id == str(provider_id))
            .one_or_none()
        )
    if actor is None:
        actor = db.query(Actor).filter(Actor.name == name).first()
    if actor is None:
        actor = Actor(name=name, provider=provider, provider_id=str(provider_id) if provider_id else None)
        db.add(actor)
        db.flush()

    img = data.get("image_url")
    if isinstance(img, str) and img:
        actor.image_url = img
    elif isinstance(img, list):
        first = _first_image(img)
        if first:
            actor.image_url = first

    if not actor.image_url:
        await enrich_actor_image(db, actor, client)
    return actor


def _as_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _first_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v)
