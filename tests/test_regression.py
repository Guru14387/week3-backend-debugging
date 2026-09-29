"""Regression tests: one test per defect that was found and fixed.

The identifiers (BUG-01 ... BUG-05) match ``DEBUGGING_REPORT.md`` and the raw
baseline evidence stored in ``artifacts/``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_bug_01_post_tasks_answers_201_created(client: TestClient) -> None:
    """Creating a resource must not answer ``200 OK``."""
    response = client.post("/tasks", json={"title": "Created task"})

    assert response.status_code == 201
    documented = client.get("/openapi.json").json()["paths"]["/tasks"]["post"]["responses"]
    assert "201" in documented
    assert "200" not in documented


def test_bug_02_update_payload_validates_the_title(client: TestClient, make_task) -> None:
    """A PATCH must not be able to blank, null or overflow a stored title."""
    task = make_task(title="Stored title")

    for bad_payload in ({"title": ""}, {"title": "   "}, {"title": None}, {"title": "x" * 201}):
        response = client.patch(f"/tasks/{task.id}", json=bad_payload)
        assert response.status_code == 422, f"payload {bad_payload} returned {response.status_code}"
        assert client.get(f"/tasks/{task.id}").json()["title"] == "Stored title"


def test_bug_02_update_also_trims_the_title(client: TestClient, make_task) -> None:
    task = make_task(title="before")

    response = client.patch(f"/tasks/{task.id}", json={"title": "  after  "})

    assert response.status_code == 200
    assert response.json()["title"] == "after"


def test_bug_03_filters_are_intersected_and_search_covers_the_description(
    client: TestClient,
    make_task,
) -> None:
    """Filtering used to behave like ``OR`` and searched the title only."""
    make_task(title="pending high", description="no keyword here", status="pending", priority="high")
    make_task(title="completed low", description="hidden burndown note", status="completed", priority="low")
    make_task(title="pending low", description="no keyword here", status="pending", priority="low")

    combined = client.get("/tasks", params={"status": "pending", "priority": "low"}).json()
    assert combined["total"] == 1
    assert [item["title"] for item in combined["items"]] == ["pending low"]

    searched = client.get("/tasks", params={"q": "burndown"}).json()
    assert searched["total"] == 1
    assert [item["title"] for item in searched["items"]] == ["completed low"]


def test_bug_04_unknown_task_returns_a_clean_404(client: TestClient) -> None:
    """A missing row must not surface as an HTTP 500 with internals."""
    response = client.get("/tasks/987654")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task 987654 not found"}
    assert "No row was found" not in response.text


def test_bug_06_due_dates_with_an_offset_are_converted_to_utc(client: TestClient) -> None:
    """A client timezone offset used to be dropped, shifting the instant."""
    response = client.post(
        "/tasks",
        json={"title": "Plan the release", "due_date": "2026-10-05T09:30:00+02:00"},
    )

    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-10-05T07:30:00"
    assert client.get(f"/tasks/{response.json()['id']}").json()["due_date"] == "2026-10-05T07:30:00"


def test_bug_06_invalid_due_dates_are_still_rejected(client: TestClient) -> None:
    """The offset handling must not swallow ordinary validation errors."""
    response = client.post("/tasks", json={"title": "Broken date", "due_date": "not-a-date"})

    assert response.status_code == 422


def test_bug_05_read_endpoints_do_not_issue_one_query_per_row(
    client: TestClient,
    make_task,
    make_comment,
    query_log: list,
) -> None:
    """The SQL statement count must not grow with the size of the page."""
    commented = make_task(title="Task with comments")
    make_comment(commented, body="first")
    make_comment(commented, body="second")
    for index in range(20):
        make_task(title=f"Task {index}")

    query_log.clear()
    small_page = client.get("/tasks", params={"limit": 1})
    small_page_statement_count = len(query_log)

    query_log.clear()
    large_page = client.get("/tasks", params={"limit": 25})
    large_page_statement_count = len(query_log)

    assert small_page.status_code == large_page.status_code == 200
    assert small_page.json()["items"][0]["comment_count"] == 2
    assert [item["comment_count"] for item in large_page.json()["items"]] == [2] + [0] * 20
    assert small_page_statement_count == large_page_statement_count
    assert large_page_statement_count <= 6
