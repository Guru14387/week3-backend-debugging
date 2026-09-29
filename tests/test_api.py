"""API integration tests: response contract, filtering, search and statistics."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app import models

EXPECTED_TASK_FIELDS = {
    "id",
    "title",
    "description",
    "status",
    "priority",
    "due_date",
    "created_at",
    "updated_at",
    "comment_count",
}


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Week3 Backend Debugging API",
        "version": "1.0.0",
    }


def test_openapi_schema_exposes_every_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) == {
        "/health",
        "/tasks",
        "/tasks/stats",
        "/tasks/{task_id}",
        "/tasks/{task_id}/comments",
    }
    assert set(paths["/tasks"]) == {"get", "post"}
    assert set(paths["/tasks/{task_id}"]) == {"get", "put", "patch", "delete"}
    assert set(paths["/tasks/{task_id}/comments"]) == {"get", "post"}


def test_post_task_returns_201_and_the_stored_resource(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "title": "Publish the debugging report",
            "description": "Week 3 deliverable",
            "priority": "high",
            "due_date": "2026-10-05T09:30:00",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == EXPECTED_TASK_FIELDS
    assert body["title"] == "Publish the debugging report"
    assert body["description"] == "Week 3 deliverable"
    assert body["status"] == "pending"
    assert body["priority"] == "high"
    assert body["due_date"] == "2026-10-05T09:30:00"
    assert body["comment_count"] == 0
    # Both columns use a Python-side default that is evaluated twice, so the two
    # timestamps may differ by a microsecond on insert - they only have to be ordered.
    assert datetime.fromisoformat(body["created_at"]) <= datetime.fromisoformat(body["updated_at"])


def test_get_task_returns_200_with_the_expected_contract(client: TestClient, make_task) -> None:
    task = make_task(title="Fetch me", priority=models.Priority.HIGH.value)

    response = client.get(f"/tasks/{task.id}")

    assert response.status_code == 200
    assert set(response.json()) == EXPECTED_TASK_FIELDS
    assert response.json()["id"] == task.id
    assert response.json()["title"] == "Fetch me"
    assert response.json()["priority"] == "high"


def test_list_tasks_paginates_and_reports_total(client: TestClient, make_task) -> None:
    for index in range(5):
        make_task(title=f"Task {index}")

    body = client.get("/tasks", params={"skip": 1, "limit": 2}).json()

    assert body["total"] == 5
    assert body["skip"] == 1
    assert body["limit"] == 2
    assert [item["title"] for item in body["items"]] == ["Task 1", "Task 2"]


def test_list_tasks_on_an_empty_database(client: TestClient) -> None:
    response = client.get("/tasks")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "skip": 0, "limit": 50}


def test_list_tasks_are_ordered_by_id(client: TestClient, make_task) -> None:
    for index in range(3):
        make_task(title=f"Task {index}")

    items = client.get("/tasks").json()["items"]

    assert [item["id"] for item in items] == sorted(item["id"] for item in items)


def test_filter_by_status(client: TestClient, make_task) -> None:
    make_task(title="pending one", status="pending")
    make_task(title="completed one", status="completed")

    body = client.get("/tasks", params={"status": "completed"}).json()

    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["completed one"]


def test_filter_by_priority(client: TestClient, make_task) -> None:
    make_task(title="urgent", priority="high")
    make_task(title="calm", priority="low")

    body = client.get("/tasks", params={"priority": "high"}).json()

    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["urgent"]


def test_filter_without_matches_returns_an_empty_page(client: TestClient, make_task) -> None:
    make_task(title="Something else")

    body = client.get("/tasks", params={"status": "completed"}).json()

    assert body["items"] == []
    assert body["total"] == 0


def test_filters_are_combined_with_and(client: TestClient, make_task) -> None:
    """BUG-03 regression: ``status`` and ``priority`` must be intersected."""
    make_task(title="A pending high", status="pending", priority="high")
    make_task(title="B completed low", status="completed", priority="low")
    make_task(title="C pending low", status="pending", priority="low")

    body = client.get("/tasks", params={"status": "pending", "priority": "low"}).json()

    assert body["total"] == 1
    assert [item["title"] for item in body["items"]] == ["C pending low"]


def test_search_matches_the_title(client: TestClient, make_task) -> None:
    make_task(title="Write the deployment script")
    make_task(title="Unrelated chore")

    body = client.get("/tasks", params={"q": "deployment"}).json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "Write the deployment script"


def test_search_matches_the_description(client: TestClient, make_task) -> None:
    """BUG-03 regression: ``q`` must also search the description column."""
    make_task(title="Improve logging", description="Add structured events for the burndown chart")
    make_task(title="Unrelated chore", description="nothing to see here")

    body = client.get("/tasks", params={"q": "burndown"}).json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "Improve logging"


def test_search_is_case_insensitive(client: TestClient, make_task) -> None:
    make_task(title="Review the migration plan")

    body = client.get("/tasks", params={"q": "MIGRATION"}).json()

    assert body["total"] == 1


def test_search_combines_with_the_other_filters(client: TestClient, make_task) -> None:
    make_task(title="Deploy staging", status="pending", priority="high")
    make_task(title="Deploy production", status="completed", priority="high")
    make_task(title="Write release notes", status="pending", priority="low")

    body = client.get(
        "/tasks",
        params={"q": "deploy", "status": "pending", "priority": "high"},
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "Deploy staging"


def test_search_without_matches_returns_an_empty_page(client: TestClient, make_task) -> None:
    make_task(title="Something else")

    body = client.get("/tasks", params={"q": "does-not-exist"}).json()

    assert body == {"items": [], "total": 0, "skip": 0, "limit": 50}


def test_statistics_endpoint_reports_backlog_counters(
    client: TestClient,
    make_task,
    make_comment,
) -> None:
    overdue = make_task(
        title="overdue",
        status="pending",
        priority="high",
        due_date=models.utcnow() - timedelta(days=3),
    )
    make_task(title="done", status="completed", priority="low")
    make_task(title="in flight", status="in_progress", priority="medium")
    make_comment(overdue)
    make_comment(overdue)

    response = client.get("/tasks/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total": 3,
        "completed": 1,
        "overdue": 1,
        "completion_rate": 0.3333,
        "by_status": {"pending": 1, "in_progress": 1, "completed": 1},
        "by_priority": {"low": 1, "medium": 1, "high": 1},
        "total_comments": 2,
        "average_comments_per_task": 0.6667,
    }


def test_statistics_on_an_empty_database(client: TestClient) -> None:
    response = client.get("/tasks/stats")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["completion_rate"] == 0.0
    assert response.json()["average_comments_per_task"] == 0.0


def test_delete_task_returns_204_without_body(client: TestClient, make_task) -> None:
    task = make_task(title="Delete me")

    response = client.delete(f"/tasks/{task.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tasks").json()["total"] == 0
