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

    Base.metadata.create_all(bind=engine)
    # Lightweight migrations for existing SQLite DBs
    _ensure_column("libraries", "auto_scan_enabled", "BOOLEAN", "0")
    _ensure_column("libraries", "scan_interval_hours", "INTEGER", None)
    _ensure_column("libraries", "scan_interval_seconds", "INTEGER", None)
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
