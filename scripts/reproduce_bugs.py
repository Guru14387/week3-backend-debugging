"""Reproduce the defects that were seeded into the baseline API.

The script drives the ASGI application through ``TestClient`` on a private
in-memory SQLite database, so it can be executed at any time without starting a
server and without touching the local development database::

    python scripts/reproduce_bugs.py

Exit code 0 means every documented defect is gone, exit code 1 means at least one
defect is still present. The output of the baseline run and of the final run is
stored in ``artifacts/``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

RESULTS: list[tuple[str, str, str, str, bool]] = []
SEED_TASKS = 30


class Harness:
    """In-memory application harness with SQL statement counting."""

    def __init__(self, task_count: int = SEED_TASKS, comments_per_task: int = 1) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(bind=self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        self.statements: list[str] = []
        event.listen(self.engine, "before_cursor_execute", self._record_statement)
        self._seed(task_count, comments_per_task)

        def _override_get_db():
            session = self.session_factory()
            try:
                yield session
            finally:
                session.close()

        fastapi_app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(fastapi_app, raise_server_exceptions=False)

    def _record_statement(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        self.statements.append(statement)

    def _seed(self, task_count: int, comments_per_task: int) -> None:
        statuses = [
            models.TaskStatus.PENDING,
            models.TaskStatus.IN_PROGRESS,
            models.TaskStatus.COMPLETED,
        ]
        priorities = [models.Priority.LOW, models.Priority.MEDIUM]
        session = self.session_factory()
        for index in range(task_count):
            task = models.Task(
                title=f"Seed task {index:02d}",
                description="mentions the burndown chart" if index % 5 == 2 else "plain seed row",
                status=statuses[index % len(statuses)].value,
                priority=priorities[index % len(priorities)].value,
            )
            for comment_index in range(comments_per_task):
                task.comments.append(models.Comment(author="script", body=f"comment {comment_index}"))
            session.add(task)
        session.commit()
        session.close()

    def close(self) -> None:
        fastapi_app.dependency_overrides.clear()
        self.engine.dispose()


def record(bug_id: str, title: str, expected: str, observed: str, fixed: bool) -> None:
    RESULTS.append((bug_id, title, expected, observed, fixed))


def check_bug_01(harness: Harness) -> None:
    response = harness.client.post("/tasks", json={"title": "Created through the API"})
    record(
        "BUG-01",
        "Wrong status code when creating a task",
        "POST /tasks -> HTTP 201 Created",
        f"POST /tasks -> HTTP {response.status_code}",
        response.status_code == 201,
    )


def check_bug_02(harness: Harness) -> None:
    task_id = harness.client.post("/tasks", json={"title": "Protected title"}).json()["id"]
    blank = harness.client.patch(f"/tasks/{task_id}", json={"title": ""})
    null_title = harness.client.patch(f"/tasks/{task_id}", json={"title": None})
    stored = harness.client.get(f"/tasks/{task_id}").json()["title"]
    record(
        "BUG-02",
        "Update endpoint accepts invalid titles",
        "PATCH title='' -> 422, PATCH title=null -> 422, stored title unchanged",
        f"PATCH title='' -> HTTP {blank.status_code}, PATCH title=null -> HTTP {null_title.status_code}, "
        f"stored title={stored!r}",
        blank.status_code == 422 and null_title.status_code == 422 and stored == "Protected title",
    )


def check_bug_03(harness: Harness) -> None:
    combined = harness.client.get("/tasks", params={"status": "pending", "priority": "low"}).json()
    searched = harness.client.get("/tasks", params={"q": "burndown"}).json()
    record(
        "BUG-03",
        "Filters behave like OR and the search ignores the description",
        "status=pending&priority=low -> 5 tasks (AND), q=burndown -> 6 tasks (description match)",
        f"status=pending&priority=low -> {combined['total']} tasks, q=burndown -> {searched['total']} tasks",
        combined["total"] == 5 and searched["total"] == 6,
    )


def check_bug_04(harness: Harness) -> None:
    response = harness.client.get("/tasks/987654")
    body = response.text.replace("\n", " ")[:70]
    record(
        "BUG-04",
        "Unknown task id returns 500 instead of 404",
        'GET /tasks/987654 -> HTTP 404 {"detail":"Task 987654 not found"}',
        f"GET /tasks/987654 -> HTTP {response.status_code} {body}",
        response.status_code == 404 and response.json() == {"detail": "Task 987654 not found"},
    )


def check_bug_05(harness: Harness) -> None:
    harness.statements.clear()
    harness.client.get("/tasks", params={"limit": 1})
    one_row = len(harness.statements)

    harness.statements.clear()
    harness.client.get("/tasks", params={"limit": SEED_TASKS})
    all_rows = len(harness.statements)

    harness.statements.clear()
    harness.client.get("/tasks/stats")
    stats = len(harness.statements)

    record(
        "BUG-05",
        "N+1 queries on the read endpoints",
        "constant statement count: limit=1 equals limit=30 and stays <= 6, GET /tasks/stats <= 8",
        f"limit=1 -> {one_row} statements, limit={SEED_TASKS} -> {all_rows} statements, stats -> {stats} statements",
        one_row == all_rows and all_rows <= 6 and stats <= 8,
    )


CHECKS: list[Callable[[Harness], None]] = [
    check_bug_01,
    check_bug_02,
    check_bug_03,
    check_bug_04,
    check_bug_05,
]


def main() -> int:
    print("=" * 100)
    print("Week3 Backend Debugging API - defect reproduction script")
    print("=" * 100)
    for check in CHECKS:
        harness = Harness()
        try:
            check(harness)
        finally:
            harness.close()

    failures = 0
    for bug_id, title, expected, observed, fixed in RESULTS:
        if not fixed:
            failures += 1
        print(f"\n{bug_id}  {title}  ->  {'FIXED / PASS' if fixed else 'DEFECT REPRODUCED / FAIL'}")
        print(f"    expected: {expected}")
        print(f"    observed: {observed}")

    print("\n" + "-" * 100)
    print(f"checks: {len(RESULTS)}   passed: {len(RESULTS) - failures}   failed: {failures}")
    print("-" * 100)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
