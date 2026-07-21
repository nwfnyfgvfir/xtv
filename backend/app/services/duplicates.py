"""Find media rows that share the same 番号 (case-insensitive)."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models import MediaItem
from app.schemas import DuplicateGroup, DuplicateMediaItem, PaginatedDuplicateGroups
from app.services.images import rewrite_image_url


def _number_key_expr():
    return func.upper(func.trim(MediaItem.number))


def list_duplicate_groups(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
) -> PaginatedDuplicateGroups:
    """Group by upper(trim(number)); return groups with count >= 2."""
    number_key = _number_key_expr()

    groups_q = (
        db.query(number_key.label("number_key"), func.count(MediaItem.id).label("cnt"))
        .filter(MediaItem.number.isnot(None), func.trim(MediaItem.number) != "")
        .group_by(number_key)
        .having(func.count(MediaItem.id) >= 2)
    )
    if q and q.strip():
        like = f"%{q.strip().upper()}%"
        groups_q = groups_q.having(number_key.like(like))

    total = (
        db.query(func.count())
        .select_from(groups_q.order_by(None).subquery())
        .scalar()
        or 0
    )

    group_rows = (
        groups_q.order_by(number_key)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if not group_rows:
        return PaginatedDuplicateGroups(items=[], total=total, page=page, page_size=page_size)

    keys = [row.number_key for row in group_rows]
    cnt_by_key = {row.number_key: int(row.cnt) for row in group_rows}

    items = (
        db.query(MediaItem)
        .options(joinedload(MediaItem.library), joinedload(MediaItem.favorite))
        .filter(MediaItem.number.isnot(None), func.trim(MediaItem.number) != "")
        .filter(number_key.in_(keys))
        .order_by(
            number_key,
            MediaItem.file_size.desc().nullslast(),
            MediaItem.id,
        )
        .all()
    )

    by_key: dict[str, list[MediaItem]] = {k: [] for k in keys}
    for item in items:
        key = (item.number or "").strip().upper()
        if key in by_key:
            by_key[key].append(item)

    groups: list[DuplicateGroup] = []
    for key in keys:
        media_list = by_key.get(key) or []
        if len(media_list) < 2:
            continue
        groups.append(
            DuplicateGroup(
                number=key,
                count=cnt_by_key.get(key, len(media_list)),
                items=[_to_duplicate_item(m) for m in media_list],
            )
        )

    return PaginatedDuplicateGroups(items=groups, total=total, page=page, page_size=page_size)


def _to_duplicate_item(item: MediaItem) -> DuplicateMediaItem:
    lib_name = item.library.name if item.library else ""
    return DuplicateMediaItem(
        id=item.id,
        library_id=item.library_id,
        filename=item.filename,
        number=item.number,
        title=item.title,
        cover_url=rewrite_image_url(
            item.cover_url, provider=item.provider, provider_id=item.provider_id
        ),
        thumb_url=rewrite_image_url(
            item.thumb_url, provider=item.provider, provider_id=item.provider_id
        ),
        source_type=item.source_type,
        provider=item.provider,
        release_date=item.release_date,
        score=item.score,
        scraped_at=item.scraped_at,
        favorited=item.favorite is not None,
        subtitle_flag=item.subtitle_flag,
        disc=item.disc,
        path=item.path,
        file_size=item.file_size,
        library_name=lib_name,
    )
