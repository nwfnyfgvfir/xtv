from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.api.actors import favorite_actor, get_actor, list_actors, unfavorite_actor
from app.api.favorites import list_favorite_actors
from app.db import SessionLocal, init_db
from app.models import Actor, ActorFavorite, Library


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


def test_favorite_and_unfavorite_actor() -> None:
    init_db()
    db = SessionLocal()
    try:
        actor = Actor(name="Star")
        db.add(actor)
        db.commit()
        db.refresh(actor)

        out = favorite_actor(actor_id=actor.id, _={}, db=db)
        assert out.favorited is True
        assert out.id == actor.id
        assert db.query(ActorFavorite).filter(ActorFavorite.actor_id == actor.id).count() == 1

        detail = get_actor(actor_id=actor.id, _={}, db=db)
        assert detail.favorited is True

        # idempotent favorite
        out2 = favorite_actor(actor_id=actor.id, _={}, db=db)
        assert out2.favorited is True
        assert db.query(ActorFavorite).filter(ActorFavorite.actor_id == actor.id).count() == 1

        out3 = unfavorite_actor(actor_id=actor.id, _={}, db=db)
        assert out3.favorited is False
        assert db.query(ActorFavorite).filter(ActorFavorite.actor_id == actor.id).count() == 0

        # idempotent unfavorite
        out4 = unfavorite_actor(actor_id=actor.id, _={}, db=db)
        assert out4.favorited is False
    finally:
        _cleanup(db)
        db.close()


def test_favorite_unknown_actor_404() -> None:
    init_db()
    db = SessionLocal()
    try:
        try:
            favorite_actor(actor_id=999999, _={}, db=db)
            raise AssertionError("expected 404")
        except HTTPException as exc:
            assert exc.status_code == 404

        try:
            unfavorite_actor(actor_id=999999, _={}, db=db)
            raise AssertionError("expected 404")
        except HTTPException as exc:
            assert exc.status_code == 404
    finally:
        db.close()


def test_list_actors_includes_favorited_flag() -> None:
    init_db()
    db = SessionLocal()
    try:
        a = Actor(name="Listed")
        b = Actor(name="Other")
        db.add_all([a, b])
        db.flush()
        db.add(ActorFavorite(actor_id=a.id))
        db.commit()

        page = list_actors(_={}, q=None, page=1, page_size=48, db=db)
        by_id = {item.id: item for item in page.items}
        assert by_id[a.id].favorited is True
        assert by_id[b.id].favorited is False
    finally:
        _cleanup(db)
        db.close()


def test_list_favorite_actors_only_favorited_ordered() -> None:
    init_db()
    db = SessionLocal()
    try:
        older = Actor(name="OlderFav")
        newer = Actor(name="NewerFav")
        plain = Actor(name="Plain")
        db.add_all([older, newer, plain])
        db.flush()
        t0 = datetime.now(timezone.utc) - timedelta(hours=2)
        t1 = datetime.now(timezone.utc) - timedelta(hours=1)
        db.add(ActorFavorite(actor_id=older.id, created_at=t0))
        db.add(ActorFavorite(actor_id=newer.id, created_at=t1))
        db.commit()

        page = list_favorite_actors(_={}, page=1, page_size=48, db=db)
        assert page.total == 2
        assert [i.name for i in page.items] == ["NewerFav", "OlderFav"]
        assert all(i.favorited for i in page.items)
        assert plain.id not in {i.id for i in page.items}
    finally:
        _cleanup(db)
        db.close()
