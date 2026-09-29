"""Behaviour tests for the task resource and its comment sub-resource."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import models


def test_full_task_lifecycle(client: TestClient) -> None:
    """Create -> read -> update -> delete -> gone."""
    created = client.post(
        "/tasks",
        json={
            "title": "Fix the login flow",
            "description": "Users are logged out after 5 minutes",
            "priority": "high",
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    fetched = client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Fix the login flow"

    patched = client.patch(f"/tasks/{task_id}", json={"status": "in_progress"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"
    assert patched.json()["title"] == "Fix the login flow"

    deleted = client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    assert client.get(f"/tasks/{task_id}").status_code == 404
    assert client.get("/tasks").json()["total"] == 0


def test_put_replaces_every_writable_field(client: TestClient, make_task) -> None:
    task = make_task(title="Old title", description="Old description", priority="high")

    response = client.put(
        f"/tasks/{task.id}",
        json={"title": "New title", "status": "completed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New title"
    assert body["status"] == "completed"
    assert body["description"] is None
    assert body["priority"] == "medium"


def test_patch_keeps_untouched_fields(client: TestClient, make_task) -> None:
    task = make_task(title="Stable title", description="Stable description", priority="high")

    response = client.patch(f"/tasks/{task.id}", json={"description": "Updated description"})

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Updated description"
    assert body["title"] == "Stable title"
    assert body["priority"] == "high"


def test_patch_with_empty_body_is_a_noop(client: TestClient, make_task) -> None:
    task = make_task(title="Untouched")

    response = client.patch(f"/tasks/{task.id}", json={})

    assert response.status_code == 200
    assert response.json()["title"] == "Untouched"


def test_patch_rejects_null_title(client: TestClient, make_task) -> None:
    """A title may not be blanked out through the API."""
    task = make_task(title="Has a title")

    response = client.patch(f"/tasks/{task.id}", json={"title": None})

    assert response.status_code == 422


def test_creating_a_task_trims_the_title(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "   Trim me   "})

    assert response.status_code == 201
    assert response.json()["title"] == "Trim me"


def test_comments_can_be_created_and_listed(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Reviewed task"}).json()["id"]

    first = client.post(f"/tasks/{task_id}/comments", json={"body": "First remark"})
    second = client.post(
        f"/tasks/{task_id}/comments",
        json={"author": "lead", "body": "Second remark"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["author"] == "anonymous"
    assert first.json()["task_id"] == task_id

    listed = client.get(f"/tasks/{task_id}/comments")
    assert listed.status_code == 200
    assert [comment["body"] for comment in listed.json()] == ["First remark", "Second remark"]

    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["comment_count"] == 2


def test_comment_count_is_exposed_for_each_listed_task(client: TestClient) -> None:
    first_id = client.post("/tasks", json={"title": "With comments"}).json()["id"]
    client.post("/tasks", json={"title": "Without comments"})
    client.post(f"/tasks/{first_id}/comments", json={"body": "note"})

    items = client.get("/tasks").json()["items"]
    counts = {item["title"]: item["comment_count"] for item in items}

    assert counts == {"With comments": 1, "Without comments": 0}


def test_deleting_a_task_removes_its_comments(
    client: TestClient,
    db_session: Session,
    make_task,
    make_comment,
) -> None:
    task = make_task(title="Has comments")
    make_comment(task, body="remove me")
    assert db_session.query(models.Comment).count() == 1

    assert client.delete(f"/tasks/{task.id}").status_code == 204

    assert db_session.query(models.Comment).count() == 0
    assert client.get(f"/tasks/{task.id}/comments").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/tasks/424242"),
        ("put", "/tasks/424242"),
        ("patch", "/tasks/424242"),
        ("delete", "/tasks/424242"),
    ],
)
def test_mutating_and_reading_unknown_tasks_returns_404(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    kwargs = {"json": {"title": "Whatever"}} if method in {"put", "patch"} else {}
    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Task 424242 not found"}
