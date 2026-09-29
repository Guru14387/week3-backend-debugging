"""Database engine, session factory and SQLite configuration.

The application uses SQLite so that the project stays self-contained: no server
process and no credentials are required to run the API or the test suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./week3_tasks.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base class shared by every ORM model."""


if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record: object) -> None:
        """SQLite ignores foreign keys unless they are switched on per connection."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create every table that is declared on :class:`Base`."""
    from app import models  # noqa: F401  (importing registers the mappers)

    Base.metadata.create_all(bind=engine)


__all__ = [
    "DATABASE_URL",
    "Base",
    "Engine",
    "SessionLocal",
    "get_db",
    "init_db",
]
