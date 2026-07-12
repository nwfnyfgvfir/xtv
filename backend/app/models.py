from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Library(Base):
    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    type: Mapped[str] = mapped_column(String(32), default="mixed", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_scan_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scan_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # legacy
    scan_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media_items: Mapped[list[MediaItem]] = relationship(back_populates="library", cascade="all, delete-orphan")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (UniqueConstraint("library_id", "path", name="uq_library_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
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


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
