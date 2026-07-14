from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: backend/app/config.py -> parents[2] = repo root
ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = f"sqlite:///{(ROOT_DIR / 'data' / 'app.db').as_posix()}"
    media_root: str = str(ROOT_DIR / "media")
    metatube_base_url: str = "https://openai-proxy.caowxj.eu.org"
    metatube_token: str = ""
    metatube_provider: str = ""  # empty = auto
    metatube_fallback: bool = True
    alist_base_url: str = "http://127.0.0.1:5244"
    alist_token: str = ""
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    host: str = "0.0.0.0"
    port: int = 8000
    scan_extensions: str = "mp4,mkv,avi,wmv,m2ts,ts,mov,strm"
    auto_scrape: bool = True
    auto_translate: bool = True
    translate_provider: str = "google"  # google | bing
    image_proxy_mode: str = "site"  # site | metatube | external
    image_external_proxy_url: str = ""  # template with {url}
    image_local_cache: bool = False
    image_cache_max_mb: int = 2048  # 0 = no prune
    log_level: str = "INFO"
    debug: bool = False
    admin_password: str = ""
    jwt_secret: str = "tv-dev-secret-change-me"
    jwt_expire_hours: int = 72
    auth_required: bool = True  # if admin_password empty, auth is effectively off

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def media_root_path(self) -> Path:
        p = Path(self.media_root)
        if not p.is_absolute():
            p = ROOT_DIR / p
        return p.resolve()

    @property
    def resolved_database_url(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///./") or url.startswith("sqlite://./"):
            rel = url.split("sqlite:///", 1)[-1].lstrip("./")
            return f"sqlite:///{(ROOT_DIR / rel).as_posix()}"
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            raw = url[len("sqlite:///") :]
            p = Path(raw)
            if not p.is_absolute():
                return f"sqlite:///{(ROOT_DIR / p).as_posix()}"
        return url

    @property
    def data_dir_path(self) -> Path:
        """Directory holding app.db (Docker: /data); fallback ROOT_DIR/data."""
        url = self.resolved_database_url
        if url.startswith("sqlite:///"):
            raw = url[len("sqlite:///") :]
            # sqlite:////data/app.db → absolute /data/app.db
            if url.startswith("sqlite:////"):
                raw = "/" + url[len("sqlite:////") :]
            p = Path(raw)
            if not p.is_absolute():
                p = ROOT_DIR / p
            try:
                return p.resolve().parent
            except OSError:
                return p.parent
        return (ROOT_DIR / "data").resolve()

    @property
    def image_cache_path(self) -> Path:
        return self.data_dir_path / "image-cache"

    @property
    def extension_set(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.scan_extensions.split(",") if e.strip()}

    @property
    def auth_enabled(self) -> bool:
        return bool(self.admin_password.strip()) and self.auth_required


@lru_cache
def get_settings() -> Settings:
    return Settings()
