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
    alist_base_url: str = "http://127.0.0.1:5244"
    alist_token: str = ""
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    host: str = "0.0.0.0"
    port: int = 8000
    scan_extensions: str = "mp4,mkv,avi,wmv,m2ts,ts,mov,strm"
    auto_scrape: bool = True

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
            # sqlite:///relative-or-absolute — if not absolute path, anchor to ROOT_DIR
            raw = url[len("sqlite:///") :]
            p = Path(raw)
            if not p.is_absolute():
                return f"sqlite:///{(ROOT_DIR / p).as_posix()}"
        return url

    @property
    def extension_set(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.scan_extensions.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
