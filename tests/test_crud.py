"""Unit tests for the data-access layer (``app.crud`` and ``app.schemas``)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app import crud, models, schemas


def test_create_task_applies_defaults(db_session: Session) -> None:
    task = crud.create_task(db_session, schemas.TaskCreate(title="Prepare demo"))

    assert task.id is not None
    assert task.status == models.TaskStatus.PENDING.value
    assert task.priority == models.Priority.MEDIUM.value
    assert task.description is None
    assert task.due_date is None
    assert task.created_at is not None
    assert task.updated_at is not None


def test_create_task_trims_the_title(db_session: Session) -> None:
    task = crud.create_task(db_session, schemas.TaskCreate(title="   padded title   "))
    assert task.title == "padded title"


def test_get_task_or_none_returns_the_row(db_session: Session, make_task) -> None:
    task = make_task(title="Look me up")
    assert crud.get_task_or_none(db_session, task.id).title == "Look me up"


def test_get_task_or_none_returns_none_for_unknown_id(db_session: Session) -> None:
    assert crud.get_task_or_none(db_session, 987654) is None


def test_list_tasks_returns_all_rows_by_default(db_session: Session, make_task) -> None:
    for index in range(3):
        make_task(title=f"Task {index}")

    items, total = crud.list_tasks(db_session)
    assert total == 3
    assert [item.title for item in items] == ["Task 0", "Task 1", "Task 2"]


def test_list_tasks_combines_filters_with_and(db_session: Session, make_task) -> None:
    """BUG-03 regression: two filters must be intersected, not unioned."""
    make_task(title="pending high", status="pending", priority="high")
    make_task(title="completed low", status="completed", priority="low")
    make_task(title="pending low", status="pending", priority="low")

    items, total = crud.list_tasks(
        db_session,
        status=models.TaskStatus.PENDING,
        priority=models.Priority.LOW,
    )
    assert total == 1
    assert [item.title for item in items] == ["pending low"]


def test_list_tasks_search_covers_title_and_description(db_session: Session, make_task) -> None:
    """BUG-03 regression: ``q`` must not be limited to the title column."""
    make_task(title="Refactor the report", description="Short note")
    make_task(title="Unrelated", description="Mentions the sprint burndown")

    items, total = crud.list_tasks(db_session, q="burndown")
    assert total == 1
    assert items[0].title == "Unrelated"


def test_list_tasks_paginates_but_reports_full_total(db_session: Session, make_task) -> None:
    for index in range(5):
        make_task(title=f"Task {index}")

    items, total = crud.list_tasks(db_session, skip=2, limit=2)
    assert total == 5
    assert [item.title for item in items] == ["Task 2", "Task 3"]


def test_to_task_read_counts_comments(db_session: Session, make_task, make_comment) -> None:
    task = make_task(title="Commented task")
    make_comment(task)
    make_comment(task, body="Second remark")

    read = crud.to_task_read(db_session, task)
    assert isinstance(read, schemas.TaskRead)
    assert read.comment_count == 2


def test_update_task_only_touches_supplied_fields(db_session: Session, make_task) -> None:
    task = make_task(title="Original", description="Keep me", priority="low")
    created_at = task.created_at

    updated = crud.update_task(
        db_session,
        task,
        schemas.TaskUpdate(status=models.TaskStatus.IN_PROGRESS),
    )

    assert updated.status == models.TaskStatus.IN_PROGRESS.value
    assert updated.title == "Original"
    assert updated.description == "Keep me"
    assert updated.priority == models.Priority.LOW.value
    assert updated.created_at == created_at


def test_replace_task_resets_omitted_fields(db_session: Session, make_task) -> None:
    task = make_task(title="Original", description="Drop me", priority="high")

    replaced = crud.replace_task(db_session, task, schemas.TaskCreate(title="Rewritten"))

    assert replaced.title == "Rewritten"
    assert replaced.description is None
    assert replaced.priority == models.Priority.MEDIUM.value
    assert replaced.status == models.TaskStatus.PENDING.value


def test_delete_task_also_removes_its_comments(db_session: Session, make_task, make_comment) -> None:
    task = make_task(title="Doomed")
    make_comment(task, body="bye")

    crud.delete_task(db_session, task)

    assert db_session.query(models.Task).count() == 0
    assert db_session.query(models.Comment).count() == 0


def test_get_statistics_aggregates_the_backlog(db_session: Session, make_task, make_comment) -> None:
    now = models.utcnow()
    overdue = make_task(
        title="overdue",
        status="pending",
        priority="high",
        due_date=now - timedelta(days=1),
    )
    completed = make_task(
        title="done",
        status="completed",
        priority="low",
        due_date=now - timedelta(days=1),
    )
    make_task(
        title="future",
        status="in_progress",
        priority="medium",
        due_date=now + timedelta(days=1),
    )

    make_comment(overdue)
    make_comment(overdue)
    make_comment(completed)

    stats = crud.get_statistics(db_session)

    assert stats.total == 3
    assert stats.completed == 1
    assert stats.overdue == 1
    assert stats.completion_rate == pytest.approx(0.3333)
    assert stats.by_status == {"pending": 1, "in_progress": 1, "completed": 1}
    assert stats.by_priority == {"low": 1, "medium": 1, "high": 1}
    assert stats.total_comments == 3
    assert stats.average_comments_per_task == pytest.approx(1.0)


def test_get_statistics_on_empty_database(db_session: Session) -> None:
    stats = crud.get_statistics(db_session)

    assert stats.total == 0
    assert stats.completed == 0
    assert stats.overdue == 0
    assert stats.completion_rate == 0.0
    assert stats.total_comments == 0
    assert stats.average_comments_per_task == 0.0
    assert stats.by_status == {"pending": 0, "in_progress": 0, "completed": 0}


def test_schema_rejects_blank_and_overlong_titles() -> None:
    for bad_title in ("", "   ", "x" * 201):
        with pytest.raises(ValueError):
            schemas.TaskCreate(title=bad_title)


def test_task_update_schema_rejects_blank_title() -> None:
    """BUG-02 regression at schema level."""
    for bad_title in ("", "   "):
        with pytest.raises(ValueError):
            schemas.TaskUpdate(title=bad_title)
