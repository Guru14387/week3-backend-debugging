"""Shared pytest fixtures: isolated in-memory database, API client, helpers.

Every test gets its own SQLite database. Because the whole app is built on
SQLite the suite runs completely offline and leaves no files behind.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (importing registers the mappers)
from app.database import Base, get_db
from app.main import app as fastapi_app


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """A fresh in-memory SQLite database shared by all connections of one test."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)
    try:
        yield test_engine
    finally:
        test_engine.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory bound to the test database."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@pytest.fixture()
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A session used by unit tests and by the seeding fixtures."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """TestClient wired to the in-memory database.

    The client is deliberately *not* used as a context manager so the application
    lifespan (which creates the file based database) does not run during tests.
    ``raise_server_exceptions=False`` returns unhandled server errors as HTTP 500
    responses - exactly what a real HTTP client would observe.
    """

    def _override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(fastapi_app, raise_server_exceptions=False)
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def query_log(engine: Engine) -> Iterator[list[str]]:
    """Record every SQL statement the application sends to the test database."""
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _insert_task(session: Session, **overrides: object) -> models.Task:
    payload: dict[str, object] = {
        "title": "Write unit tests",
        "description": "Cover the CRUD layer",
        "status": models.TaskStatus.PENDING.value,
        "priority": models.Priority.MEDIUM.value,
    }
    payload.update(overrides)
    task = models.Task(**payload)
    session.add(task)
    session.commit()
    return task


@pytest.fixture()
def make_task(db_session: Session) -> Callable[..., models.Task]:
    """Insert a task directly through the ORM (independent of the HTTP layer)."""

    def factory(**overrides: object) -> models.Task:
        return _insert_task(db_session, **overrides)

    return factory


@pytest.fixture()
def make_comment(db_session: Session) -> Callable[..., models.Comment]:
    """Attach a comment to an existing task directly through the ORM."""

    def factory(task: models.Task, **overrides: object) -> models.Comment:
        payload: dict[str, object] = {
            "task_id": task.id,
            "author": "reviewer",
            "body": "Looks good to me",
        }
        payload.update(overrides)
        comment = models.Comment(**payload)
        db_session.add(comment)
        db_session.commit()
        return comment

    return factory
