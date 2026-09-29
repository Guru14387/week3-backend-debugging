"""Pydantic request/response models for the task API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.models import Priority, TaskStatus

MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000


def _validate_title(value: object) -> object:
    """Trim a title and reject empty/whitespace-only or over-long values."""
    if not isinstance(value, str):
        return value  # let the ``str`` type produce the regular validation error
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("title must not be empty or whitespace-only")
    if len(cleaned) > MAX_TITLE_LENGTH:
        raise ValueError(f"title must be at most {MAX_TITLE_LENGTH} characters long")
    return cleaned


def _normalise_due_date(value: object) -> object:
    """Store timestamps as naive UTC so comparisons never mix aware/naive values.

    The request body always delivers the value as a string, so the offset has to be
    parsed here. SQLite drops ``tzinfo`` when the value is stored, which would
    silently shift the instant by the offset sent by the client.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value  # let the regular "invalid date" validation report it
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


Title = Annotated[str, BeforeValidator(_validate_title)]
Description = Annotated[str | None, Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)]
DueDate = Annotated[datetime | None, BeforeValidator(_normalise_due_date)]


class APIModel(BaseModel):
    """Shared configuration: ORM objects are accepted and typos are rejected."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class TaskCreate(APIModel):
    """Payload for ``POST /tasks`` and ``PUT /tasks/{task_id}``."""

    title: Title
    description: Description = None
    status: TaskStatus = TaskStatus.PENDING
    priority: Priority = Priority.MEDIUM
    due_date: DueDate = None


class TaskUpdate(APIModel):
    """Payload for ``PATCH /tasks/{task_id}`` - every field is optional."""

    title: Title | None = None
    description: Description = None
    status: TaskStatus | None = None
    priority: Priority | None = None
    due_date: DueDate = None

    @field_validator("title", mode="before")
    @classmethod
    def _reject_null_title(cls, value: object) -> object:
        """``null`` would violate the NOT NULL constraint, so reject it early."""
        if value is None:
            raise ValueError("title cannot be null - omit the field to keep the current title")
        return value


class CommentCreate(APIModel):
    """Payload for ``POST /tasks/{task_id}/comments``."""

    author: Annotated[str, Field(min_length=1, max_length=100)] = "anonymous"
    body: Annotated[str, Field(min_length=1, max_length=MAX_DESCRIPTION_LENGTH)]


class TaskRead(APIModel):
    """A task as returned by the API."""

    id: int
    title: str
    description: str | None = None
    status: TaskStatus
    priority: Priority
    due_date: datetime | None = None
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0


class CommentRead(APIModel):
    """A comment as returned by the API."""

    id: int
    task_id: int
    author: str
    body: str
    created_at: datetime


class TaskList(APIModel):
    """One page of tasks plus the total number of matching rows."""

    items: list[TaskRead]
    total: int
    skip: int
    limit: int


class TaskStatistics(APIModel):
    """Aggregated counters for ``GET /tasks/stats``."""

    total: int
    completed: int
    overdue: int
    completion_rate: float
    by_status: dict[str, int]
    by_priority: dict[str, int]
    total_comments: int
    average_comments_per_task: float


class HealthStatus(APIModel):
    """Response body of the ``/health`` probe."""

    status: str
    service: str
    version: str


__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_TITLE_LENGTH",
    "APIModel",
    "CommentCreate",
    "CommentRead",
    "Description",
    "DueDate",
    "HealthStatus",
    "TaskCreate",
    "TaskList",
    "TaskRead",
    "TaskStatistics",
    "TaskUpdate",
    "Title",
]
