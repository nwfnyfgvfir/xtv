from __future__ import annotations

import asyncio

from app.db import SessionLocal, init_db
from app.models import Actor, Library, MediaActor, MediaItem
from app.services.actors import (
    dedupe_actors,
    delete_orphan_actors,
    merge_actors,
    pick_canonical,
)
from app.services.scrape import _apply_translations, _set_actor_provider_safe, _upsert_actor


def _cleanup(db) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass
    for lib in db.query(Library).all():
        db.delete(lib)
    db.flush()
    for actor in db.query(Actor).all():
        db.delete(actor)
    db.commit()


def _media(db, lib: Library, filename: str) -> MediaItem:
    item = MediaItem(
        library_id=lib.id,
        path=f"/tmp/{lib.id}/{filename}",
        filename=filename,
        source_type="local",
    )
    db.add(item)
    db.flush()
    return item


def test_merge_actors_moves_links_and_fills_fields() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = Library(name="t", path="p", type="local")
        db.add(lib)
        db.flush()
        m1 = _media(db, lib, "a.mp4")
        m2 = _media(db, lib, "b.mp4")

        keep = Actor(name="Alice", provider=None, provider_id=None, image_url=None)
        drop = Actor(name="Alice", provider="Gfriends", provider_id="1", image_url="http://img/a.jpg")
        db.add_all([keep, drop])
        db.flush()
        db.add_all(
            [
                MediaActor(media_id=m1.id, actor_id=keep.id),
                MediaActor(media_id=m2.id, actor_id=drop.id),
            ]
        )
        db.flush()

        result = merge_actors(db, keep=keep, drop=drop)
        db.commit()

        assert result.id == keep.id
        assert db.get(Actor, drop.id) is None
        assert result.image_url == "http://img/a.jpg"
        assert result.provider == "Gfriends"
        assert result.provider_id == "1"
        media_ids = {
            row.media_id for row in db.query(MediaActor).filter(MediaActor.actor_id == keep.id).all()
        }
        assert media_ids == {m1.id, m2.id}
    finally:
        _cleanup(db)
        db.close()


def test_merge_actors_skips_duplicate_media_link() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = Library(name="t", path="p2", type="local")
        db.add(lib)
        db.flush()
        m1 = _media(db, lib, "c.mp4")

        keep = Actor(name="Bob")
        drop = Actor(name="Bob")
        db.add_all([keep, drop])
        db.flush()
        db.add_all(
            [
                MediaActor(media_id=m1.id, actor_id=keep.id),
                MediaActor(media_id=m1.id, actor_id=drop.id),
            ]
        )
        db.flush()

        merge_actors(db, keep=keep, drop=drop)
        db.commit()

        links = db.query(MediaActor).filter(MediaActor.media_id == m1.id).all()
        assert len(links) == 1
        assert links[0].actor_id == keep.id
        assert db.query(Actor).filter(Actor.name == "Bob").count() == 1
    finally:
        _cleanup(db)
        db.close()


def test_set_actor_provider_safe_merges_on_collision() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = Library(name="t", path="p3", type="local")
        db.add(lib)
        db.flush()
        m1 = _media(db, lib, "d.mp4")
        m2 = _media(db, lib, "e.mp4")

        owner = Actor(name="Carol", provider="Gfriends", provider_id="c1")
        other = Actor(name="Carol")
        db.add_all([owner, other])
        db.flush()
        db.add_all(
            [
                MediaActor(media_id=m1.id, actor_id=owner.id),
                MediaActor(media_id=m2.id, actor_id=other.id),
            ]
        )
        db.flush()
        other_id = other.id

        result = _set_actor_provider_safe(db, other, "Gfriends", "c1")
        db.commit()

        assert result.id == owner.id
        assert db.get(Actor, other_id) is None
        media_ids = {
            row.media_id for row in db.query(MediaActor).filter(MediaActor.actor_id == owner.id).all()
        }
        assert media_ids == {m1.id, m2.id}
    finally:
        _cleanup(db)
        db.close()


def test_upsert_merges_duplicate_names() -> None:
    init_db()
    db = SessionLocal()
    try:
        a1 = Actor(name="Dana")
        a2 = Actor(name="Dana", image_url="http://img/d.jpg")
        db.add_all([a1, a2])
        db.flush()

        class _Dummy:
            token = ""

        result = asyncio.run(_upsert_actor(db, _Dummy(), {"name": "Dana"}))  # type: ignore[arg-type]
        db.commit()

        assert result is not None
        assert db.query(Actor).filter(Actor.name == "Dana").count() == 1
        assert result.image_url == "http://img/d.jpg"
    finally:
        _cleanup(db)
        db.close()


def test_upsert_skips_empty_name() -> None:
    init_db()
    db = SessionLocal()
    try:

        class _Dummy:
            token = ""

        result = asyncio.run(_upsert_actor(db, _Dummy(), {"name": "   "}))  # type: ignore[arg-type]
        assert result is None
    finally:
        db.close()


def test_apply_translations_does_not_rename_actors(monkeypatch) -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = Library(name="t", path="p4", type="local")
        db.add(lib)
        db.flush()
        item = _media(db, lib, "f.mp4")
        item.title = "title"
        item.plot = "plot"
        actor = Actor(name="原文名")
        db.add(actor)
        db.flush()
        item.actors.append(actor)
        db.flush()

        async def fake_translate(text: str) -> str:
            return f"ZH:{text}"

        async def fake_tags(tags: list[str]) -> list[str]:
            return [f"ZH:{t}" for t in tags]

        monkeypatch.setattr("app.services.translate.translate_text", fake_translate)
        monkeypatch.setattr("app.services.translate.translate_tags", fake_tags)

        asyncio.run(
            _apply_translations(db, item, src_title="title", src_plot="plot", tags=["tag"])
        )
        db.commit()
        db.refresh(actor)
        assert actor.name == "原文名"
        assert item.title == "ZH:title"
    finally:
        _cleanup(db)
        db.close()


def test_delete_orphan_actors_only_unreferenced() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = Library(name="t", path="p5", type="local")
        db.add(lib)
        db.flush()
        m1 = _media(db, lib, "g.mp4")
        used = Actor(name="Used")
        orphan = Actor(name="Orphan")
        db.add_all([used, orphan])
        db.flush()
        db.add(MediaActor(media_id=m1.id, actor_id=used.id))
        db.flush()

        n = delete_orphan_actors(db)
        db.commit()
        assert n == 1
        assert db.query(Actor).filter(Actor.name == "Used").count() == 1
        assert db.query(Actor).filter(Actor.name == "Orphan").count() == 0
    finally:
        _cleanup(db)
        db.close()


def test_delete_library_removes_orphan_actors_keeps_shared() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib_a = Library(name="A", path="pa", type="local")
        lib_b = Library(name="B", path="pb", type="local")
        db.add_all([lib_a, lib_b])
        db.flush()
        ma = _media(db, lib_a, "ha.mp4")
        mb = _media(db, lib_b, "hb.mp4")
        only_a = Actor(name="OnlyA")
        shared = Actor(name="Shared")
        db.add_all([only_a, shared])
        db.flush()
        db.add_all(
            [
                MediaActor(media_id=ma.id, actor_id=only_a.id),
                MediaActor(media_id=ma.id, actor_id=shared.id),
                MediaActor(media_id=mb.id, actor_id=shared.id),
            ]
        )
        db.commit()

        # Simulate delete_library: delete lib A then orphan cleanup
        db.delete(lib_a)
        db.flush()
        delete_orphan_actors(db)
        db.commit()

        assert db.query(Actor).filter(Actor.name == "OnlyA").count() == 0
        assert db.query(Actor).filter(Actor.name == "Shared").count() == 1

        db.delete(lib_b)
        db.flush()
        delete_orphan_actors(db)
        db.commit()
        assert db.query(Actor).filter(Actor.name == "Shared").count() == 0
    finally:
        _cleanup(db)
        db.close()


def test_dedupe_actors_by_name() -> None:
    init_db()
    db = SessionLocal()
    try:
        lib = Library(name="t", path="p6", type="local")
        db.add(lib)
        db.flush()
        m1 = _media(db, lib, "i.mp4")
        m2 = _media(db, lib, "j.mp4")
        a1 = Actor(name="Eve")
        a2 = Actor(name="Eve", provider="Gfriends", provider_id="e1", image_url="http://e")
        a3 = Actor(name=" Eve ")  # trimmed match
        db.add_all([a1, a2, a3])
        db.flush()
        db.add_all(
            [
                MediaActor(media_id=m1.id, actor_id=a1.id),
                MediaActor(media_id=m2.id, actor_id=a3.id),
            ]
        )
        db.flush()

        dropped = dedupe_actors(db)
        db.commit()
        assert dropped >= 2
        # All should merge into one; name may be stripped on keep
        all_named = [a for a in db.query(Actor).all() if normalize_like_eve(a.name)]
        assert len(all_named) == 1
        keep = all_named[0]
        assert keep.provider == "Gfriends"
        media_ids = {
            row.media_id for row in db.query(MediaActor).filter(MediaActor.actor_id == keep.id).all()
        }
        assert media_ids == {m1.id, m2.id}
    finally:
        _cleanup(db)
        db.close()


def normalize_like_eve(name: str | None) -> bool:
    return (name or "").strip() == "Eve"


def test_pick_canonical_prefers_provider_then_image() -> None:
    bare = Actor(id=1, name="x")
    imaged = Actor(id=2, name="x", image_url="http://i")
    keyed = Actor(id=3, name="x", provider="p", provider_id="1")
    assert pick_canonical([bare, imaged, keyed]).id == 3
    assert pick_canonical([bare, imaged]).id == 2
