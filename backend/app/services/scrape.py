from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Actor, MediaItem
from app.services.actors import merge_actors, normalize_actor_name, pick_canonical
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


def _priority_list_from_settings(settings: Settings | Any) -> list[str]:
    raw = getattr(settings, "metatube_provider_priority", "") or ""
    if isinstance(raw, list):
        data = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in data:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


async def _search_with_chain(
    client: MetaTubeClient,
    number: str,
    *,
    chain: list[str],
    use_fallback: bool,
    force_auto: bool,
) -> list[dict[str, Any]]:
    """
    Search MetaTube using an ordered provider chain.

    force_auto=True → single search provider="" with fallback=use_fallback.
    Else try each chain entry with fallback=False; stop on first _pick_best hit.
    If no hit and (not chain or use_fallback): final search provider="" fallback=True
    (or use_fallback when chain empty and not force_auto).
    """
    if force_auto:
        logger.info("scrape try %s provider=auto fallback=%s", number, use_fallback)
        return await client.search_movie(number, provider="", fallback=use_fallback)

    results: list[dict[str, Any]] = []
    for p in chain:
        logger.info("scrape try %s provider=%s", number, p)
        results = await client.search_movie(number, provider=p, fallback=False)
        if _pick_best(results, number):
            return results

    if not chain:
        logger.info("scrape try %s provider=auto fallback=%s", number, use_fallback)
        return await client.search_movie(number, provider="", fallback=use_fallback)

    if use_fallback:
        logger.info("scrape try %s provider=auto fallback=true (after chain)", number)
        return await client.search_movie(number, provider="", fallback=True)

    return results


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
            name = normalize_actor_name(a)
            if name:
                out.append({"name": name})
        elif isinstance(a, dict):
            name = normalize_actor_name(a.get("name") or a.get("Name"))
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
        priority = _priority_list_from_settings(settings)
        default_fallback = (
            fallback_override if fallback_override is not None else settings.metatube_fallback
        )

        if provider_override is not None:
            if provider_override == "":
                force_auto = True
                chain: list[str] = []
            else:
                force_auto = False
                chain = [provider_override]
            use_fallback = default_fallback
        elif priority:
            force_auto = False
            chain = priority
            use_fallback = default_fallback
        elif settings.metatube_provider:
            force_auto = False
            chain = [settings.metatube_provider]
            use_fallback = default_fallback
        else:
            force_auto = False
            chain = []
            use_fallback = True if fallback_override is None else bool(fallback_override)

        results = await _search_with_chain(
            client,
            item.number,
            chain=chain,
            use_fallback=use_fallback,
            force_auto=force_auto,
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

        src_title = detail.get("title") or best.get("title") or item.title
        src_plot = (
            detail.get("summary")
            or detail.get("plot")
            or detail.get("description")
            or item.plot
        )
        item.title = src_title
        item.plot = src_plot
        item.provider = provider or item.provider
        item.provider_id = provider_id or item.provider_id

        # Store ORIGINAL source URLs; API layer rewrites via image proxy mode.
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

        tags: list[str] = []
        genres = detail.get("genres") or detail.get("tags") or []
        if isinstance(genres, list) and genres:
            tags = [g if isinstance(g, str) else str(g.get("name", g)) for g in genres]
            if item.subtitle_flag == "C" and "中文字幕" not in tags:
                tags.append("中文字幕")
            item.tags_json = json.dumps(tags, ensure_ascii=False)
        elif item.subtitle_flag == "C":
            tags = ["中文字幕"]
            item.tags_json = json.dumps(tags, ensure_ascii=False)

        item.actors.clear()
        for a in _actor_list(detail):
            actor = await _upsert_actor(db, client, a)
            if actor is not None and actor not in item.actors:
                item.actors.append(actor)

        if settings.auto_translate:
            await _apply_translations(db, item, src_title=src_title, src_plot=src_plot, tags=tags)

        item.scraped_at = datetime.now(timezone.utc)
        db.add(item)
        db.commit()
        db.refresh(item)
        return True
    except MetaTubeError as exc:
        logger.warning("scrape failed for %s: %s", item.number, exc)
        db.rollback()
        return False
    except Exception as exc:  # noqa: BLE001
        # Avoid lazy-loading expired attributes after a failed flush.
        number = getattr(item, "number", None) or "?"
        try:
            logger.exception("unexpected scrape error for %s: %s", number, exc)
        except Exception:  # noqa: BLE001
            logger.exception("unexpected scrape error")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


async def _apply_translations(
    db: Session,
    item: MediaItem,
    *,
    src_title: str | None,
    src_plot: str | None,
    tags: list[str],
) -> None:
    """Translate title/plot/tags in-place. Actor names are identity — not translated."""
    from app.services.translate import translate_tags, translate_text

    # Always refresh originals from pre-translate MetaTube strings
    if src_title:
        item.title_original = str(src_title)[:512]
    if src_plot:
        item.plot_original = str(src_plot)

    if item.title:
        item.title = await translate_text(item.title)
    if item.plot:
        item.plot = await translate_text(item.plot)

    if tags:
        translated_tags = await translate_tags(tags)
        item.tags_json = json.dumps(translated_tags, ensure_ascii=False)


def _set_actor_provider_safe(
    db: Session,
    actor: Actor,
    provider: str | None,
    provider_id: str | None,
) -> Actor:
    """Assign provider keys; on collision merge actor into the key owner."""
    if not provider or not provider_id:
        return actor
    pid = str(provider_id)
    existing = (
        db.query(Actor)
        .filter(Actor.provider == provider, Actor.provider_id == pid)
        .one_or_none()
    )
    if existing is not None and existing.id != actor.id:
        # Provider key is stronger identity → keep existing, drop actor.
        return merge_actors(db, keep=existing, drop=actor)
    if not actor.provider:
        actor.provider = provider
    if not actor.provider_id:
        actor.provider_id = pid
    return actor


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
        actor = _set_actor_provider_safe(
            db,
            actor,
            str(best.get("provider") or "Gfriends"),
            str(best.get("id") or actor.name),
        )
        db.add(actor)
        # Flush only — caller owns the outer transaction/commit.
        try:
            db.flush()
        except Exception:  # noqa: BLE001
            logger.debug("actor image flush failed %s", actor.name, exc_info=True)
            # Do not rollback outer scrape transaction; leave image unset.
            return False
        return True
    except MetaTubeError as exc:
        logger.debug("actor image scrape failed %s: %s", actor.name, exc)
        return False
    except Exception:  # noqa: BLE001
        logger.debug("actor image scrape error %s", actor.name, exc_info=True)
        return False


async def _upsert_actor(db: Session, client: MetaTubeClient, data: dict[str, Any]) -> Actor | None:
    name = normalize_actor_name(str(data.get("name") or ""))
    if not name:
        return None
    provider = data.get("provider")
    provider_id = data.get("provider_id")
    actor: Actor | None = None

    # 1) Provider key
    if provider and provider_id:
        actor = (
            db.query(Actor)
            .filter(Actor.provider == provider, Actor.provider_id == str(provider_id))
            .one_or_none()
        )

    # 2) Exact name — merge duplicates if multiple rows share the name
    if actor is None:
        matches = db.query(Actor).filter(Actor.name == name).all()
        if matches:
            actor = pick_canonical(matches)
            for other in matches:
                if other.id != actor.id:
                    actor = merge_actors(db, keep=actor, drop=other)

    # 3) Create
    if actor is None:
        actor = Actor(
            name=name,
            provider=str(provider) if provider else None,
            provider_id=str(provider_id) if provider_id else None,
        )
        db.add(actor)
        try:
            db.flush()
        except Exception:  # noqa: BLE001
            # Concurrent insert of same provider key — re-query existing row.
            db.rollback()
            actor = None
            if provider and provider_id:
                actor = (
                    db.query(Actor)
                    .filter(Actor.provider == provider, Actor.provider_id == str(provider_id))
                    .one_or_none()
                )
            if actor is None:
                matches = db.query(Actor).filter(Actor.name == name).all()
                if matches:
                    actor = pick_canonical(matches)
                    for other in matches:
                        if other.id != actor.id:
                            actor = merge_actors(db, keep=actor, drop=other)
            if actor is None:
                actor = Actor(name=name)
                db.add(actor)
                db.flush()
    else:
        actor = _set_actor_provider_safe(
            db,
            actor,
            str(provider) if provider else None,
            str(provider_id) if provider_id else None,
        )

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
