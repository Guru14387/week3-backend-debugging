"""SQLAlchemy ORM models and the domain enumerations used across the API."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TaskStatus(enum.StrEnum):
    """Lifecycle states a task can be in."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class Priority(enum.StrEnum):
    """Relative importance of a task."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def utcnow() -> datetime:
    """Return a naive UTC timestamp (SQLite cannot store tz-aware datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Task(Base):
    """A single unit of work tracked by the API."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TaskStatus.PENDING.value,
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=Priority.MEDIUM.value,
        index=True,
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    comments: Mapped[list["Comment"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Task id={self.id} status={self.status!r} title={self.title!r}>"


class Comment(Base):
    """A free-text note attached to a task."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author: Mapped[str] = mapped_column(String(100), nullable=False, default="anonymous")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="comments")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Comment id={self.id} task_id={self.task_id}>"


__all__ = ["Comment", "Priority", "Task", "TaskStatus", "utcnow"]
