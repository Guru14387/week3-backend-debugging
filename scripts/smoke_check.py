"""Start the API with uvicorn and drive it over real HTTP.

This is the "does the application actually start and serve requests" check::

    python scripts/smoke_check.py

A child ``uvicorn`` process is started on a free port with a temporary SQLite
database, ``/health`` is polled until the server answers and then a complete task
lifecycle is executed with ``httpx``. The server is shut down again afterwards.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT_SECONDS = 40.0

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    if not condition:
        FAILURES.append(label)
    print(f"[{status}] {label}{f' -> {detail}' if detail else ''}")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_health(client: httpx.Client, base_url: str) -> dict[str, object] | None:
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            response = client.get(f"{base_url}/health")
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            time.sleep(0.25)
    return None


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory() as tmp_dir:
        env = dict(os.environ)
        env["DATABASE_URL"] = f"sqlite:///{Path(tmp_dir, 'smoke_check.db').as_posix()}"
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            print(f"starting: {sys.executable} -m uvicorn app.main:app --port {port} (cwd={PROJECT_ROOT})")
            with httpx.Client(timeout=10.0) as client:
                health = wait_for_health(client, base_url)
                check("uvicorn started and /health answered", health is not None, f"{base_url}/health")
                if health is None:
                    return 1
                print(f"        payload: {health}")

                openapi = client.get(f"{base_url}/openapi.json")
                paths = sorted(openapi.json()["paths"]) if openapi.status_code == 200 else []
                check(
                    "OpenAPI document exposes every route",
                    paths
                    == ["/health", "/tasks", "/tasks/stats", "/tasks/{task_id}", "/tasks/{task_id}/comments"],
                    f"{paths}",
                )

                created = client.post(
                    f"{base_url}/tasks",
                    json={"title": "Smoke check task", "priority": "high"},
                )
                check("POST /tasks answers 201", created.status_code == 201, f"HTTP {created.status_code}")
                task_id = created.json()["id"]

                fetched = client.get(f"{base_url}/tasks/{task_id}")
                check("GET /tasks/{id} answers 200", fetched.status_code == 200, f"HTTP {fetched.status_code}")

                patched = client.patch(f"{base_url}/tasks/{task_id}", json={"status": "in_progress"})
                check(
                    "PATCH /tasks/{id} stores the new status",
                    patched.status_code == 200 and patched.json()["status"] == "in_progress",
                    f"HTTP {patched.status_code}",
                )

                commented = client.post(f"{base_url}/tasks/{task_id}/comments", json={"body": "smoke"})
                check(
                    "POST /tasks/{id}/comments answers 201",
                    commented.status_code == 201,
                    f"HTTP {commented.status_code}",
                )

                filtered = client.get(f"{base_url}/tasks", params={"status": "in_progress", "q": "smoke"})
                check(
                    "GET /tasks?status=&q= applies both filters",
                    filtered.status_code == 200 and filtered.json()["total"] == 1,
                    f"HTTP {filtered.status_code} total={filtered.json().get('total')}",
                )

                stats = client.get(f"{base_url}/tasks/stats")
                check(
                    "GET /tasks/stats aggregates the backlog",
                    stats.status_code == 200
                    and stats.json()["total"] == 1
                    and stats.json()["total_comments"] == 1,
                    f"HTTP {stats.status_code} {stats.json() if stats.status_code == 200 else ''}",
                )

                deleted = client.delete(f"{base_url}/tasks/{task_id}")
                check("DELETE /tasks/{id} answers 204", deleted.status_code == 204, f"HTTP {deleted.status_code}")

                missing = client.get(f"{base_url}/tasks/{task_id}")
                check(
                    "GET /tasks/{id} answers 404 once deleted",
                    missing.status_code == 404,
                    f"HTTP {missing.status_code} {missing.text}",
                )

                unknown = client.get(f"{base_url}/tasks/987654")
                check(
                    "GET /tasks/987654 answers a clean 404",
                    unknown.status_code == 404 and unknown.json() == {"detail": "Task 987654 not found"},
                    f"HTTP {unknown.status_code} {unknown.text}",
                )
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                server.kill()
            output = server.stdout.read() if server.stdout else ""
            if output.strip():
                print("\n--- uvicorn output ---")
                print(output.strip())

    print("-" * 80)
    print(f"checks failed: {len(FAILURES)}")
    for failure in FAILURES:
        print(f"  - {failure}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
