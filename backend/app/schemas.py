from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    type: Literal["local", "strm", "mixed"] = "mixed"
    enabled: bool = True
    auto_scan_enabled: bool = False
    scan_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    scan_interval_seconds: int | None = Field(default=None, ge=30, le=30 * 24 * 3600)


class LibraryUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    type: Literal["local", "strm", "mixed"] | None = None
    enabled: bool | None = None
    auto_scan_enabled: bool | None = None
    scan_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    scan_interval_seconds: int | None = Field(default=None, ge=30, le=30 * 24 * 3600)


class LibraryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    path: str
    type: str
    enabled: bool
    auto_scan_enabled: bool = False
    scan_interval_hours: int | None = None
    scan_interval_seconds: int | None = None
    media_count: int = 0
    # In-process LibraryChanged generation (bumped on ingest/remove/scrape).
    content_revision: int = 0
    created_at: datetime


class BrowseDirEntry(BaseModel):
    name: str
    path: str  # relative to MEDIA_ROOT, posix


class BrowseDirsOut(BaseModel):
    path: str
    parent: str | None = None
    directories: list[BrowseDirEntry]


class ActorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str | None = None
    provider_id: str | None = None
    image_url: str | None = None
    favorited: bool = False


class ActorListItem(ActorOut):
    media_count: int = 0


class ActorDetail(ActorListItem):
    pass


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
    favorited: bool = False
    subtitle_flag: str | None = None
    disc: str | None = None


class MediaDetail(MediaListItem):
    path: str
    plot: str | None = None
    provider_id: str | None = None
    runtime: int | None = None
    studio: str | None = None
    backdrop_url: str | None = None
    strm_target: str | None = None
    tags_json: str | None = None
    file_size: int | None = None
    created_at: datetime
    updated_at: datetime
    actors: list[ActorOut] = []


class RescrapeIn(BaseModel):
    provider: str | None = None
    fallback: bool | None = None
    number: str | None = None  # optional override / fill-in 番号


class PaginatedMedia(BaseModel):
    items: list[MediaListItem]
    total: int
    page: int
    page_size: int


class PaginatedActors(BaseModel):
    items: list[ActorListItem]
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
    metatube_provider: str = ""
    metatube_provider_priority: list[str] = []
    metatube_fallback: bool = True
    alist_base_url: str
    alist_token_set: bool
    media_root: str
    auto_scrape: bool
    auto_translate: bool = True
    translate_provider: Literal["google", "bing"] = "google"
    image_proxy_mode: Literal["site", "metatube", "external"] = "site"
    image_external_proxy_url: str = ""
    image_local_cache: bool = False
    scan_extensions: str
    cors_origins: str
    auth_enabled: bool = False
    movie_providers: list[str] = []
    movie_providers_error: str | None = None
    movie_providers_from_cache: bool = False
    extra: dict[str, str] = {}


class SettingsUpdate(BaseModel):
    metatube_base_url: str | None = None
    metatube_token: str | None = None
    metatube_provider: str | None = None
    metatube_provider_priority: list[str] | None = None
    metatube_fallback: bool | None = None
    alist_base_url: str | None = None
    alist_token: str | None = None
    auto_scrape: bool | None = None
    auto_translate: bool | None = None
    translate_provider: Literal["google", "bing"] | None = None
    image_proxy_mode: Literal["site", "metatube", "external"] | None = None
    image_external_proxy_url: str | None = None
    image_local_cache: bool | None = None
    scan_extensions: str | None = None
    extra: dict[str, str] | None = None


class ScanJobOut(BaseModel):
    job_id: str
    status: str
    library_id: int | None = None
    scanned: int = 0
    created: int = 0
    scraped: int = 0
    removed: int = 0
    errors: list[str] = []
    message: str | None = None


class HealthOut(BaseModel):
    status: str
    metatube: dict[str, Any] | None = None
    auth_enabled: bool = False
    scheduler: dict[str, Any] | None = None


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    auth_enabled: bool = True


class AuthStatusOut(BaseModel):
    auth_enabled: bool
    authenticated: bool
