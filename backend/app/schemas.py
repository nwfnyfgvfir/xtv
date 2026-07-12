from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    type: Literal["local", "strm", "mixed"] = "mixed"
    enabled: bool = True


class LibraryUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    type: Literal["local", "strm", "mixed"] | None = None
    enabled: bool | None = None


class LibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    path: str
    type: str
    enabled: bool
    created_at: datetime


class ActorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str | None = None
    provider_id: str | None = None
    image_url: str | None = None


class MediaListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    library_id: int
    filename: str
    number: str | None = None
    title: str | None = None
    cover_url: str | None = None
    thumb_url: str | None = None
    source_type: str
    provider: str | None = None
    release_date: str | None = None
    score: float | None = None
    scraped_at: datetime | None = None


class MediaDetail(MediaListItem):
    path: str
    plot: str | None = None
    provider_id: str | None = None
    runtime: int | None = None
    studio: str | None = None
    backdrop_url: str | None = None
    strm_target: str | None = None
    tags_json: str | None = None
    disc: str | None = None
    subtitle_flag: str | None = None
    file_size: int | None = None
    created_at: datetime
    updated_at: datetime
    actors: list[ActorOut] = []


class PaginatedMedia(BaseModel):
    items: list[MediaListItem]
    total: int
    page: int
    page_size: int


class PlayInfo(BaseModel):
    play_url: str
    kind: Literal["local", "direct", "alist"]
    headers: dict[str, str] | None = None


class ProgressIn(BaseModel):
    position_sec: float = 0
    duration_sec: float | None = None


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    media_id: int
    position_sec: float
    duration_sec: float | None = None
    updated_at: datetime | None = None


class SettingsOut(BaseModel):
    metatube_base_url: str
    metatube_token_set: bool
    alist_base_url: str
    alist_token_set: bool
    media_root: str
    auto_scrape: bool
    scan_extensions: str
    cors_origins: str
    extra: dict[str, str] = {}


class SettingsUpdate(BaseModel):
    metatube_base_url: str | None = None
    metatube_token: str | None = None
    alist_base_url: str | None = None
    alist_token: str | None = None
    auto_scrape: bool | None = None
    scan_extensions: str | None = None
    extra: dict[str, str] | None = None


class ScanJobOut(BaseModel):
    job_id: str
    status: str
    library_id: int | None = None
    scanned: int = 0
    created: int = 0
    scraped: int = 0
    errors: list[str] = []
    message: str | None = None


class HealthOut(BaseModel):
    status: str
    metatube: dict[str, Any] | None = None
