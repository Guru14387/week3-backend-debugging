"""Data-access helpers for tasks and comments.

The module keeps the service layer thin: routes delegate to these functions and
only deal with HTTP concerns (status codes, response models).
"""

from __future__ import annotations

import enum

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app import models, schemas


def _as_column_value(value: object) -> object:
    """Convert enum members into the raw value stored in the database."""
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _apply_values(task: models.Task, data: dict[str, object]) -> None:
    for field, value in data.items():
        setattr(task, field, _as_column_value(value))


# --------------------------------------------------------------------------- tasks


def create_task(db: Session, payload: schemas.TaskCreate) -> models.Task:
    """Persist a new task and return the stored row."""
    task = models.Task(
        title=payload.title,
        description=payload.description,
        status=_as_column_value(payload.status),
        priority=_as_column_value(payload.priority),
        due_date=payload.due_date,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> models.Task:
    """Return the task with ``task_id``."""
    return db.query(models.Task).filter(models.Task.id == task_id).one()


def get_task_or_none(db: Session, task_id: int) -> models.Task | None:
    """Return the task with ``task_id`` or ``None`` when it does not exist."""
    return db.query(models.Task).filter(models.Task.id == task_id).one_or_none()


def _build_filter(
    status: models.TaskStatus | None,
    priority: models.Priority | None,
    q: str | None,
):
    """Translate the query-string arguments into a single ``AND`` filter clause."""
    conditions = []
    if status is not None:
        conditions.append(models.Task.status == _as_column_value(status))
    if priority is not None:
        conditions.append(models.Task.priority == _as_column_value(priority))
    if q:
        pattern = f"%{q}%"
        conditions.append(
            or_(
                models.Task.title.ilike(pattern),
                models.Task.description.ilike(pattern),
            )
        )
    if not conditions:
        return None
    return and_(*conditions)


def list_tasks(
    db: Session,
    status: models.TaskStatus | None = None,
    priority: models.Priority | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[models.Task], int]:
    """Return one page of tasks together with the total amount of matches."""
    query = db.query(models.Task)
    clause = _build_filter(status=status, priority=priority, q=q)
    if clause is not None:
        query = query.filter(clause)

    total = query.count()
    items = query.order_by(models.Task.id).offset(skip).limit(limit).all()
    return list(items), total


def to_task_read(db: Session, task: models.Task) -> schemas.TaskRead:
    """Serialise a task, including the number of comments attached to it."""
    read = schemas.TaskRead.model_validate(task)
    return read.model_copy(update={"comment_count": len(task.comments)})


def replace_task(db: Session, task: models.Task, payload: schemas.TaskCreate) -> models.Task:
    """Full update - fields that are not part of the payload fall back to defaults."""
    _apply_values(task, payload.model_dump())
    db.commit()
    db.refresh(task)
    return task


def update_task(db: Session, task: models.Task, payload: schemas.TaskUpdate) -> models.Task:
    """Partial update - only the fields sent by the client are changed."""
    _apply_values(task, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: models.Task) -> None:
    """Delete a task and its comments."""
    db.delete(task)
    db.commit()


# ------------------------------------------------------------------------ comments


def create_comment(db: Session, task: models.Task, payload: schemas.CommentCreate) -> models.Comment:
    """Attach a comment to an existing task."""
    comment = models.Comment(task_id=task.id, author=payload.author, body=payload.body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def list_comments(db: Session, task_id: int) -> list[models.Comment]:
    """Return every comment of a task ordered by creation time."""
    return (
        db.query(models.Comment)
        .filter(models.Comment.task_id == task_id)
        .order_by(models.Comment.id)
        .all()
    )


# --------------------------------------------------------------------- statistics


def get_statistics(db: Session) -> schemas.TaskStatistics:
    """Aggregate counters describing the whole task backlog."""
    tasks = db.query(models.Task).all()

    by_status = {status.value: 0 for status in models.TaskStatus}
    by_priority = {priority.value: 0 for priority in models.Priority}
    total_comments = 0
    overdue = 0
    now = models.utcnow()

    for task in tasks:
        by_status[task.status] = by_status.get(task.status, 0) + 1
        by_priority[task.priority] = by_priority.get(task.priority, 0) + 1

        comments = task.comments
        total_comments += len(comments)

        if task.due_date is not None and task.due_date < now and task.status != models.TaskStatus.COMPLETED.value:
            overdue += 1

    total = len(tasks)
    completed = by_status.get(models.TaskStatus.COMPLETED.value, 0)
    return schemas.TaskStatistics(
        total=total,
        completed=completed,
        overdue=overdue,
        completion_rate=round(completed / total, 4) if total else 0.0,
        by_status=by_status,
        by_priority=by_priority,
        total_comments=total_comments,
        average_comments_per_task=round(total_comments / total, 4) if total else 0.0,
    )


__all__ = [
    "create_comment",
    "create_task",
    "delete_task",
    "get_statistics",
    "get_task",
    "get_task_or_none",
    "list_comments",
    "list_tasks",
    "replace_task",
    "to_task_read",
    "update_task",
]
