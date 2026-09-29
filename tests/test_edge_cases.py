"""Edge cases: validation, boundaries and error handling."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("bad_title", ["", "   ", "\t\n"])
def test_create_rejects_blank_titles(client: TestClient, bad_title: str) -> None:
    response = client.post("/tasks", json={"title": bad_title})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "title"]


def test_create_rejects_a_title_that_is_too_long(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "x" * 201}).status_code == 422


def test_create_accepts_a_title_of_exactly_200_characters(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "x" * 200}).status_code == 201


def test_create_rejects_a_missing_title(client: TestClient) -> None:
    assert client.post("/tasks", json={"description": "no title here"}).status_code == 422


def test_create_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "Valid", "colour": "blue"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("bad_status", ["DONE", "open", 1, None])
def test_create_rejects_unknown_status_values(client: TestClient, bad_status: object) -> None:
    response = client.post("/tasks", json={"title": "Valid", "status": bad_status})

    assert response.status_code == 422


def test_create_rejects_an_invalid_due_date(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "Valid", "due_date": "not-a-date"}).status_code == 422


def test_create_normalises_timezone_aware_due_dates(client: TestClient) -> None:
    response = client.post("/tasks", json={"title": "Valid", "due_date": "2026-10-05T09:30:00+02:00"})

    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-10-05T07:30:00"


def test_create_rejects_an_overlong_description(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "Valid", "description": "x" * 2001}).status_code == 422


def test_create_accepts_a_description_of_exactly_2000_characters(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": "Valid", "description": "x" * 2000}).status_code == 201


@pytest.mark.parametrize("bad_title", ["", "   "])
def test_patch_rejects_blank_titles(client: TestClient, make_task, bad_title: str) -> None:
    """BUG-02 regression: an empty string must not blank out a stored title."""
    task = make_task(title="Keep this title")

    response = client.patch(f"/tasks/{task.id}", json={"title": bad_title})

    assert response.status_code == 422
    assert client.get(f"/tasks/{task.id}").json()["title"] == "Keep this title"


def test_patch_trims_the_title(client: TestClient, make_task) -> None:
    """BUG-02 regression: patched titles get the same treatment as created ones."""
    task = make_task(title="Before")

    response = client.patch(f"/tasks/{task.id}", json={"title": "   After   "})

    assert response.status_code == 200
    assert response.json()["title"] == "After"


def test_patch_rejects_a_null_title(client: TestClient, make_task) -> None:
    """BUG-02 regression: ``null`` used to reach the database and raise 500."""
    task = make_task(title="Keep this title")

    response = client.patch(f"/tasks/{task.id}", json={"title": None})

    assert response.status_code == 422
    assert client.get(f"/tasks/{task.id}").json()["title"] == "Keep this title"


def test_patch_rejects_an_overlong_title(client: TestClient, make_task) -> None:
    task = make_task(title="Before")

    assert client.patch(f"/tasks/{task.id}", json={"title": "x" * 201}).status_code == 422


def test_patch_rejects_unknown_fields(client: TestClient, make_task) -> None:
    task = make_task(title="Valid")

    response = client.patch(f"/tasks/{task.id}", json={"titel": "typo"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_put_rejects_blank_titles(client: TestClient, make_task) -> None:
    task = make_task(title="Before")

    assert client.put(f"/tasks/{task.id}", json={"title": ""}).status_code == 422


def test_unknown_task_id_returns_404_not_500(client: TestClient) -> None:
    """BUG-04 regression: missing rows must map to 404, never to 500."""
    response = client.get("/tasks/987654")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task 987654 not found"}


def test_error_responses_do_not_leak_internal_details(client: TestClient) -> None:
    """BUG-04 regression: the previous handler echoed the SQLAlchemy message."""
    payload = client.get("/tasks/987654").text

    assert "No row was found" not in payload
    assert "Traceback" not in payload
    assert "sqlalchemy" not in payload.lower()


def test_non_integer_task_id_is_rejected(client: TestClient) -> None:
    assert client.get("/tasks/not-a-number").status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"limit": -5},
        {"skip": -1},
        {"q": ""},
        {"status": "nope"},
        {"priority": "urgent"},
    ],
)
def test_invalid_query_parameters_are_rejected(client: TestClient, params: dict[str, object]) -> None:
    assert client.get("/tasks", params=params).status_code == 422


def test_paging_beyond_the_last_page_returns_no_items(client: TestClient, make_task) -> None:
    for index in range(3):
        make_task(title=f"Task {index}")

    body = client.get("/tasks", params={"skip": 10, "limit": 5}).json()

    assert body["items"] == []
    assert body["total"] == 3
    assert body["skip"] == 10


def test_deleting_the_same_task_twice_returns_404_the_second_time(client: TestClient, make_task) -> None:
    task = make_task(title="Delete me once")

    assert client.delete(f"/tasks/{task.id}").status_code == 204
    assert client.delete(f"/tasks/{task.id}").status_code == 404


def test_comment_on_an_unknown_task_returns_404(client: TestClient) -> None:
    assert client.post("/tasks/987654/comments", json={"body": "hello?"}).status_code == 404


def test_comment_rejects_an_empty_body(client: TestClient, make_task) -> None:
    task = make_task(title="Valid")

    assert client.post(f"/tasks/{task.id}/comments", json={"body": ""}).status_code == 422


def test_comment_accepts_a_single_character_body(client: TestClient, make_task) -> None:
    task = make_task(title="Valid")

    assert client.post(f"/tasks/{task.id}/comments", json={"body": "!"}).status_code == 201


def test_comment_rejects_an_overlong_body(client: TestClient, make_task) -> None:
    task = make_task(title="Valid")

    assert client.post(f"/tasks/{task.id}/comments", json={"body": "x" * 2001}).status_code == 422


def test_comments_of_an_unknown_task_return_404(client: TestClient) -> None:
    assert client.get("/tasks/987654/comments").status_code == 404


def test_unicode_payloads_are_stored_verbatim(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "title": "Réparer le cache d'import",
            "description": "Vérifier les accents é è ê",
        },
    )

    assert response.status_code == 201
    task_id = response.json()["id"]
    assert response.json()["title"] == "Réparer le cache d'import"
    assert client.get(f"/tasks/{task_id}").json()["description"] == "Vérifier les accents é è ê"


def test_null_description_and_due_date_round_trip(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Minimal task"})

    assert created.status_code == 201
    assert created.json()["description"] is None
    assert created.json()["due_date"] is None
