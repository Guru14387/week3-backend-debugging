"""Task and comment endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _require_task(db: Session, task_id: int) -> models.Task:
    """Fetch a task or answer ``404`` when the identifier is unknown."""
    task = crud.get_task_or_none(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    return task


@router.post(
    "",
    response_model=schemas.TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
def create_task(payload: schemas.TaskCreate, db: Session = Depends(get_db)) -> schemas.TaskRead:
    """Create a new task."""
    task = crud.create_task(db, payload)
    return crud.to_task_read(db, task)


@router.get("", response_model=schemas.TaskList, summary="List, filter and search tasks")
def list_tasks(
    task_status: models.TaskStatus | None = Query(default=None, alias="status"),
    priority: models.Priority | None = Query(default=None),
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=200,
        description="Case-insensitive substring search across title and description.",
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> schemas.TaskList:
    """Return a page of tasks; filters are combined with AND semantics."""
    items, total = crud.list_tasks(
        db,
        status=task_status,
        priority=priority,
        q=q,
        skip=skip,
        limit=limit,
    )
    return schemas.TaskList(
        items=[crud.to_task_read(db, task) for task in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/stats", response_model=schemas.TaskStatistics, summary="Aggregated task statistics")
def task_statistics(db: Session = Depends(get_db)) -> schemas.TaskStatistics:
    """Return backlog counters (declared before ``/{task_id}`` on purpose)."""
    return crud.get_statistics(db)


@router.get("/{task_id}", response_model=schemas.TaskRead, summary="Get one task")
def read_task(task_id: int, db: Session = Depends(get_db)) -> schemas.TaskRead:
    """Return a single task; answers ``404`` when the identifier is unknown."""
    task = _require_task(db, task_id)
    return crud.to_task_read(db, task)


@router.put("/{task_id}", response_model=schemas.TaskRead, summary="Replace a task")
def replace_task(
    task_id: int,
    payload: schemas.TaskCreate,
    db: Session = Depends(get_db),
) -> schemas.TaskRead:
    """Replace every writable field of a task."""
    task = _require_task(db, task_id)
    updated = crud.replace_task(db, task, payload)
    return crud.to_task_read(db, updated)


@router.patch("/{task_id}", response_model=schemas.TaskRead, summary="Update a task")
def update_task(
    task_id: int,
    payload: schemas.TaskUpdate,
    db: Session = Depends(get_db),
) -> schemas.TaskRead:
    """Update only the fields present in the request body."""
    task = _require_task(db, task_id)
    updated = crud.update_task(db, task, payload)
    return crud.to_task_read(db, updated)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a task")
def delete_task(task_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a task and every comment attached to it."""
    task = _require_task(db, task_id)
    crud.delete_task(db, task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{task_id}/comments",
    response_model=schemas.CommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a comment to a task",
)
def create_comment(
    task_id: int,
    payload: schemas.CommentCreate,
    db: Session = Depends(get_db),
) -> schemas.CommentRead:
    """Attach a comment to an existing task."""
    task = _require_task(db, task_id)
    return crud.create_comment(db, task, payload)


@router.get(
    "/{task_id}/comments",
    response_model=list[schemas.CommentRead],
    summary="List the comments of a task",
)
def list_comments(task_id: int, db: Session = Depends(get_db)) -> list[schemas.CommentRead]:
    """Return every comment attached to a task."""
    _require_task(db, task_id)
    return crud.list_comments(db, task_id)
