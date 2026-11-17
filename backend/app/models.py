from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    active_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    library_id: Mapped[int | None] = mapped_column(ForeignKey("libraries.id", ondelete="SET NULL"), index=True)
    library_name: Mapped[str] = mapped_column(String(128), default="")
    media_id: Mapped[int | None] = mapped_column(Integer, index=True)
    media_label: Mapped[str | None] = mapped_column(String(512))
    parent_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    manifest_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    phase: Mapped[str] = mapped_column(String(32), default="queued")
    message: Mapped[str | None] = mapped_column(Text)
    current: Mapped[str | None] = mapped_column(String(512))
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    scraped: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    waiting: Mapped[int] = mapped_column(Integer, default=0)
    scan_manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    items: Mapped[list[BackgroundJobItem]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class BackgroundJobItem(Base):
    __tablename__ = "background_job_items"
    __table_args__ = (
        UniqueConstraint("job_id", "item_key", name="uq_job_item"),
        Index("ix_task_item_pending", "job_id", "status", "id"),
        Index("ix_task_item_phase", "job_id", "phase", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("background_jobs.job_id", ondelete="CASCADE"), index=True)
    item_key: Mapped[str] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(512))
    path: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Library(Base):
    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="mixed", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_scan_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Compatibility only: automatic monitoring always uses native events.
    scan_mode: Mapped[str] = mapped_column(String(16), default="native", nullable=False)
    ts_policy: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    # Legacy scheduling columns are retained for upgrades; no periodic full scan uses them.
    full_scan_interval_seconds: Mapped[int] = mapped_column(Integer, default=86400, nullable=False)
    next_full_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_settle_seconds: Mapped[int | None] = mapped_column(Integer)
    parent_fallback_depth: Mapped[int | None] = mapped_column(Integer)
    ignore_dirs: Mapped[str | None] = mapped_column(Text)
    scan_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # legacy
    scan_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)  # legacy
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media_items: Mapped[list[MediaItem]] = relationship(back_populates="library", cascade="all, delete-orphan")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (UniqueConstraint("library_id", "path", name="uq_library_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    number: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    # Legacy columns remain readable; locks and parent recognition no longer affect queries.
    number_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    number_source: Mapped[str | None] = mapped_column(String(24))
    recognition_notes: Mapped[str | None] = mapped_column(Text)
    recognition_version: Mapped[str | None] = mapped_column(String(64))
    file_mtime_ns: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title_original: Mapped[str | None] = mapped_column(String(512), nullable=True)
    plot: Mapped[str | None] = mapped_column(Text, nullable=True)
    plot_original: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)
    studio: Mapped[str | None] = mapped_column(String(256), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    thumb_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    backdrop_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    strm_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    disc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subtitle_flag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    library: Mapped[Library] = relationship(back_populates="media_items")
    actors: Mapped[list[Actor]] = relationship(secondary="media_actors", back_populates="media_items")
    progress: Mapped[PlaybackProgress | None] = relationship(
        back_populates="media", uselist=False, cascade="all, delete-orphan"
    )
    favorite: Mapped[Favorite | None] = relationship(
        back_populates="media", uselist=False, cascade="all, delete-orphan"
    )


class Actor(Base):
    __tablename__ = "actors"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="uq_actor_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    media_items: Mapped[list[MediaItem]] = relationship(secondary="media_actors", back_populates="actors")
    favorite: Mapped[ActorFavorite | None] = relationship(
        back_populates="actor", uselist=False, cascade="all, delete-orphan"
    )


class MediaActor(Base):
    __tablename__ = "media_actors"

    media_id: Mapped[int] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"), primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True)


class PlaybackProgress(Base):
    __tablename__ = "playback_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("media_items.id", ondelete="CASCADE"), unique=True, nullable=False)
    position_sec: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    media: Mapped[MediaItem] = relationship(back_populates="progress")


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    media_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media: Mapped[MediaItem] = relationship(back_populates="favorite")


class ActorFavorite(Base):
    __tablename__ = "actor_favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("actors.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    actor: Mapped[Actor] = relationship(back_populates="favorite")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class FileObservation(Base):
    __tablename__ = "file_observations"
    __table_args__ = (UniqueConstraint("library_id", "path", name="uq_observed_path"),
                     Index("ix_observation_due", "state", "next_check_at"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int | None] = mapped_column(Integer)
    mtime_ns: Mapped[str | None] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(24), default="waiting")
    reason: Mapped[str] = mapped_column(Text, default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
