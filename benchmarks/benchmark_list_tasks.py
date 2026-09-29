"""Local benchmark for the read endpoints of the API.

Measures two things per request:

* the number of SQL statements the application sends to SQLite (deterministic,
  the metric that exposes the N+1 pattern), and
* the wall-clock latency (median of several runs on this machine).

Usage::

    python benchmarks/benchmark_list_tasks.py --tasks 200 --comments 1

Only measured values are printed; nothing is estimated.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
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

N_PLUS_ONE_THRESHOLD = 10


def build_harness(task_count: int, comments_per_task: int):
    """Create an in-memory database seeded with ``task_count`` tasks."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    statuses = [models.TaskStatus.PENDING, models.TaskStatus.IN_PROGRESS, models.TaskStatus.COMPLETED]
    priorities = [models.Priority.LOW, models.Priority.MEDIUM, models.Priority.HIGH]

    session = session_factory()
    for index in range(task_count):
        task = models.Task(
            title=f"Benchmark task {index:04d}",
            description="benchmark seed row",
            status=statuses[index % len(statuses)].value,
            priority=priorities[index % len(priorities)].value,
        )
        for comment_index in range(comments_per_task):
            task.comments.append(models.Comment(author="benchmark", body=f"comment {comment_index}"))
        session.add(task)
    session.commit()
    session.close()

    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    def _override_get_db():
        db_session = session_factory()
        try:
            yield db_session
        finally:
            db_session.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    return engine, client, statements, session_factory


def measure(client: TestClient, statements: list[str], path: str, repeats: int) -> dict[str, object]:
    """Return statement count and latency statistics for a single request."""
    client.get(path)  # warm-up: opens the connection and caches the statements
    statements.clear()
    response = client.get(path)
    statements_per_request = len(statements)

    timings_ms = []
    for _ in range(repeats):
        started = time.perf_counter()
        response = client.get(path)
        timings_ms.append((time.perf_counter() - started) * 1000.0)

    return {
        "path": path,
        "status": response.status_code,
        "statements": statements_per_request,
        "median_ms": statistics.median(timings_ms),
        "min_ms": min(timings_ms),
        "max_ms": max(timings_ms),
        "body": response.json(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark the read endpoints of the API.")
    parser.add_argument("--tasks", type=int, default=200, help="number of seeded tasks (default: 200)")
    parser.add_argument("--comments", type=int, default=1, help="comments per task (default: 1)")
    parser.add_argument("--repeats", type=int, default=5, help="timed repetitions per request (default: 5)")
    args = parser.parse_args()

    engine, client, statements, session_factory = build_harness(args.tasks, args.comments)
    try:
        session = session_factory()
        first_task_id = session.query(models.Task.id).order_by(models.Task.id).first()[0]
        session.close()

        print("=" * 100)
        print("Week3 Backend Debugging API - read endpoint benchmark")
        print(f"seed: {args.tasks} tasks x {args.comments} comment(s), in-memory SQLite, "
              f"{args.repeats} timed repetitions per request")
        print("=" * 100)

        results = [
            measure(client, statements, f"/tasks?limit={args.tasks}", args.repeats),
            measure(client, statements, "/tasks/stats", args.repeats),
            measure(client, statements, f"/tasks/{first_task_id}", args.repeats),
        ]

        header = f"{'request':<28}{'status':>7}{'SQL stmts':>11}{'median ms':>12}{'min ms':>10}{'max ms':>10}"
        print(header)
        print("-" * len(header))
        for result in results:
            print(
                f"{str(result['path']):<28}{int(result['status']):>7}{int(result['statements']):>11}"
                f"{float(result['median_ms']):>12.1f}{float(result['min_ms']):>10.1f}{float(result['max_ms']):>10.1f}"
            )

        listing_body = results[0]["body"]
        stats_body = results[1]["body"]
        print("\npayload sanity checks")
        print("-" * len(header))
        print(f"GET /tasks            -> total={listing_body['total']}, "
              f"items={len(listing_body['items'])}, "
              f"comment_count of the first item={listing_body['items'][0]['comment_count']}")
        print(f"GET /tasks/stats      -> total={stats_body['total']}, "
              f"total_comments={stats_body['total_comments']}, "
              f"by_status={stats_body['by_status']}")

        listing_statements = int(results[0]["statements"])
        print("\nverdict")
        print("-" * len(header))
        looks_like_n_plus_one = listing_statements > N_PLUS_ONE_THRESHOLD
        print(f"statements for 'GET /tasks?limit={args.tasks}' : {listing_statements}")
        print(f"N+1 pattern detected                          : {'YES' if looks_like_n_plus_one else 'NO'}")
        return 0
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

