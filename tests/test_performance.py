"""Performance regression tests.

The read endpoints used to run one extra ``SELECT`` per task - the classic N+1
pattern. These tests count the SQL statements the application actually sends and
require that count to stay constant while the number of rows grows.

Run them on their own with::

    pytest -m performance -v
"""

from __future__ import annotations

import statistics
import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.performance

PAGE_SIZE_TASKS = 40
BENCHMARK_TASKS = 200
LATENCY_BUDGET_SECONDS = 1.0


def test_list_statement_count_does_not_grow_with_the_page(
    client: TestClient,
    make_task,
    make_comment,
    query_log: list[str],
) -> None:
    for index in range(PAGE_SIZE_TASKS):
        task = make_task(title=f"Task {index:03d}")
        make_comment(task, body="first")
        make_comment(task, body="second")

    query_log.clear()
    small_page = client.get("/tasks", params={"limit": 5})
    small_page_statements = len(query_log)

    query_log.clear()
    full_page = client.get("/tasks", params={"limit": PAGE_SIZE_TASKS})
    full_page_statements = len(query_log)

    print(
        f"\n[tasks] limit=5 -> {small_page_statements} statements, "
        f"limit={PAGE_SIZE_TASKS} -> {full_page_statements} statements"
    )

    assert small_page.status_code == full_page.status_code == 200
    assert small_page.json()["total"] == PAGE_SIZE_TASKS
    assert all(item["comment_count"] == 2 for item in full_page.json()["items"])
    assert small_page_statements == full_page_statements
    assert full_page_statements <= 6


def test_statistics_statement_count_is_constant(
    client: TestClient,
    make_task,
    make_comment,
    query_log: list[str],
) -> None:
    for index in range(5):
        make_comment(make_task(title=f"small backlog {index}"))

    query_log.clear()
    client.get("/tasks/stats")
    small_backlog_statements = len(query_log)

    for index in range(35):
        make_task(title=f"large backlog {index}")

    query_log.clear()
    response = client.get("/tasks/stats")
    large_backlog_statements = len(query_log)

    print(
        f"\n[stats] 5 tasks -> {small_backlog_statements} statements, "
        f"40 tasks -> {large_backlog_statements} statements"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 40
    assert response.json()["total_comments"] == 5
    assert small_backlog_statements == large_backlog_statements
    assert large_backlog_statements <= 8


def test_single_task_lookup_is_cheap(
    client: TestClient,
    make_task,
    make_comment,
    query_log: list[str],
) -> None:
    task = make_task(title="Single lookup")
    make_comment(task)
    make_comment(task, body="and another")

    query_log.clear()
    response = client.get(f"/tasks/{task.id}")
    statements = len(query_log)

    print(f"\n[tasks/{{id}}] {statements} statements")

    assert response.status_code == 200
    assert response.json()["comment_count"] == 2
    assert statements <= 4


def test_comment_lookup_is_cheap(client: TestClient, make_task, make_comment, query_log: list[str]) -> None:
    task = make_task(title="With comments")
    make_comment(task, body="only one")

    query_log.clear()
    response = client.get(f"/tasks/{task.id}/comments")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert len(query_log) <= 4


def test_list_latency_budget_for_a_large_page(
    client: TestClient,
    make_task,
    make_comment,
) -> None:
    """A page of 200 tasks with comments must stay well below one second."""
    for index in range(BENCHMARK_TASKS):
        make_comment(make_task(title=f"Benchmark task {index:03d}"), body="note")

    client.get("/tasks", params={"limit": 200})  # warm-up

    timings = []
    for _ in range(5):
        started = time.perf_counter()
        response = client.get("/tasks", params={"limit": 200})
        timings.append(time.perf_counter() - started)

    median_seconds = statistics.median(timings)
    print(
        f"\n[latency] GET /tasks?limit=200 over {BENCHMARK_TASKS} tasks with comments: "
        f"median {median_seconds * 1000:.1f} ms "
        f"(min {min(timings) * 1000:.1f} ms / max {max(timings) * 1000:.1f} ms)"
    )

    assert response.status_code == 200
    assert response.json()["total"] == BENCHMARK_TASKS
    assert median_seconds < LATENCY_BUDGET_SECONDS
