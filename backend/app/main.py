from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import get_settings
from app.db import init_db
from app.logging_setup import configure_logging
from app.services.scheduler import shutdown_scheduler, start_scheduler
from app.services.watcher import start_watcher, stop_watcher

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Re-apply after uvicorn may have installed its own loggers/handlers.
    configure_logging()
    init_db()
    settings = get_settings()
    settings.media_root_path.mkdir(parents=True, exist_ok=True)
    (settings.media_root_path / "local").mkdir(parents=True, exist_ok=True)
    (settings.media_root_path / "strm").mkdir(parents=True, exist_ok=True)
    if not settings.auth_enabled:
        logger.warning("ADMIN_PASSWORD empty — API auth is DISABLED (dev mode)")
    try:
        start_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to start scheduler")
    try:
        start_watcher()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to start filesystem watcher")
    yield
    try:
        stop_watcher()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to stop filesystem watcher")
    try:
        shutdown_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to stop scheduler")


app = FastAPI(title="TV", version="0.2.0", lifespan=lifespan)
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

static_dir = Path(__file__).resolve().parent / "static"
index_html = static_dir / "index.html"
if index_html.is_file():
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith("api"):
            return {"detail": "Not Found"}
        file_path = static_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(index_html)
