"""SQLite/WAL engine and Alembic migrations for the MVP single writer."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[2]


def sqlite_url(path: Path) -> str:
    return "sqlite:///" + str(path.resolve())


def create_database_engine(url: str) -> Engine:
    if not url.startswith("sqlite:///"):
        raise ValueError("MVP only supports SQLite with one dispatcher writer")
    engine = create_engine(url, connect_args={"timeout": 10, "check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def migrate(url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@contextmanager
def write_tx(engine: Engine) -> Iterator[Session]:
    """BEGIN IMMEDIATE serializes claim/receipt/outbox as one SQLite transaction."""
    with Session(engine, expire_on_commit=False) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
