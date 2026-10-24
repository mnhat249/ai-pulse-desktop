from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _apply_pragmas(dbapi_conn: sqlite3.Connection, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(db_path: Path) -> AsyncEngine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    return engine


def _alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _current_revision(db_path: Path) -> str | None:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def migrate(db_path: Path, backup_dir: Path | None = None) -> None:
    """Nâng DB lên phiên bản mới nhất; sao lưu trước khi đổi cấu trúc DB đã có dữ liệu."""
    cfg = _alembic_config(db_path)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if db_path.exists():
        current = _current_revision(db_path)
        if current == head:
            return
        if current is not None and backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = backup_dir / f"neuralradar-{stamp}-{current}.db"
            backup_database(db_path, target)
            logger.info("Đã sao lưu DB trước khi migrate: %s", target)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(cfg, "head")
    _enable_wal(db_path)
    logger.info("DB đã ở phiên bản %s", head)


def backup_database(db_path: Path, target: Path) -> None:
    """Sao lưu nhất quán bằng API backup của SQLite, gồm cả dữ liệu còn trong file `-wal`."""
    source = sqlite3.connect(db_path, timeout=5)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()


def _enable_wal(db_path: Path) -> None:
    """WAL được lưu trong file DB; bật một lần lúc khởi động để các kết nối sau không tranh khóa."""
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
