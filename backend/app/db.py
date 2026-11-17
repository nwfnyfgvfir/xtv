from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.resolved_database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if "///" in url:
            from pathlib import Path

            raw = url.split("///", 1)[1]
            Path(raw).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args, future=True)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_column(table: str, column: str, ddl_type: str, default_sql: str | None = None) -> None:
    insp = inspect(engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return
    clause = f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
    if default_sql is not None:
        clause += f" DEFAULT {default_sql}"
    logger.info("Migrating schema: %s", clause)
    with engine.begin() as conn:
        conn.execute(text(clause))


def init_db() -> None:
    from app import models  # noqa: F401

    existing = inspect(engine)
    old_scan_policy = "libraries" in existing.get_table_names() and "scan_mode" not in {c["name"] for c in existing.get_columns("libraries")}
    Base.metadata.create_all(bind=engine)
    # Lightweight migrations for existing SQLite DBs
    _ensure_column("libraries", "auto_scan_enabled", "BOOLEAN", "0")
    _ensure_column("libraries", "scan_interval_hours", "INTEGER", None)
    _ensure_column("libraries", "scan_interval_seconds", "INTEGER", None)
    _ensure_column("media_items", "title_original", "TEXT", None)
    _ensure_column("media_items", "plot_original", "TEXT", None)
    for column, ddl, default in (
        ("ts_policy", "VARCHAR(16)", "'auto'"),
        ("full_scan_interval_seconds", "INTEGER", "86400"),
        ("next_full_scan_at", "DATETIME", None), ("file_settle_seconds", "INTEGER", None),
        ("parent_fallback_depth", "INTEGER", None), ("ignore_dirs", "TEXT", None),
    ):
        _ensure_column("libraries", column, ddl, default)
    for column, ddl, default in (
        ("number_locked", "BOOLEAN", "0"), ("number_source", "VARCHAR(24)", None),
        ("recognition_notes", "TEXT", None), ("recognition_version", "VARCHAR(64)", None),
        ("file_mtime_ns", "VARCHAR(32)", None),
    ):
        _ensure_column("media_items", column, ddl, default)
    _ensure_column("background_jobs", "waiting", "INTEGER", "0")
    _ensure_column("background_jobs", "scan_manifest_json", "TEXT", "'{}'")
    if old_scan_policy:
        # Legacy auto_scan_enabled was unused: preserve monitoring, at a lower rate.
        with engine.begin() as conn:
            conn.execute(text("UPDATE libraries SET auto_scan_enabled=enabled, scan_interval_seconds=CASE WHEN scan_interval_seconds>=30 THEN scan_interval_seconds ELSE 120 END"))
    # Add the migration marker last so an interrupted upgrade can run again.
    _ensure_column("libraries", "scan_mode", "VARCHAR(16)", "'poll'")
    # Backfill seconds from legacy hours when empty
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE libraries SET scan_interval_seconds = scan_interval_hours * 3600 "
                    "WHERE scan_interval_seconds IS NULL AND scan_interval_hours IS NOT NULL"
                )
            )
    except Exception:  # noqa: BLE001
        logger.debug("scan_interval backfill skipped", exc_info=True)

    _run_actor_dedupe_once()


ACTOR_DEDUPE_KEY = "actors_deduped_v1"


def _run_actor_dedupe_once() -> None:
    """One-shot merge of duplicate actors + orphan cleanup for existing DBs."""
    from app.models import AppSetting
    from app.services.actors import dedupe_actors, delete_orphan_actors

    db = SessionLocal()
    try:
        flag = db.get(AppSetting, ACTOR_DEDUPE_KEY)
        if flag and flag.value == "1":
            return
        merged = dedupe_actors(db)
        orphans = delete_orphan_actors(db)
        db.merge(AppSetting(key=ACTOR_DEDUPE_KEY, value="1"))
        db.commit()
        logger.info("Actor cleanup: merged=%s orphans_deleted=%s", merged, orphans)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Actor dedupe failed")
    finally:
        db.close()
