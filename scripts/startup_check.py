"""Startup check with the *default* configuration (file based SQLite database).

Unlike ``smoke_check.py`` (which uses a throw-away database) this script verifies the
default path that a developer gets out of the box::

    python scripts/startup_check.py

It starts ``uvicorn app.main:app`` without overriding ``DATABASE_URL``, waits for
``/health``, confirms that ``week3_tasks.db`` was created by the application lifespan and
then shuts the server down again and removes the file it created.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT_SECONDS = 40.0
DATABASE_FILE = PROJECT_ROOT / "week3_tasks.db"

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        FAILURES.append(label)
    print(f"[{'PASS' if condition else 'FAIL'}] {label}{f' -> {detail}' if detail else ''}")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    if DATABASE_FILE.exists():
        print(f"removing the pre-existing {DATABASE_FILE.name} to make the check meaningful")
        DATABASE_FILE.unlink()

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        print(f"starting: python -m uvicorn app.main:app --port {port} (default DATABASE_URL)")
        payload = None
        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        with httpx.Client(timeout=10.0) as client:
            while time.time() < deadline and payload is None:
                try:
                    response = client.get(f"{base_url}/health")
                    if response.status_code == 200:
                        payload = response.json()
                except httpx.HTTPError:
                    time.sleep(0.25)

        check("uvicorn starts with the default file database and /health answers", payload is not None)
        if payload is not None:
            print(f"        payload: {payload}")
        check(f"{DATABASE_FILE.name} was created by the startup hook", DATABASE_FILE.exists())
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            server.kill()
        output = server.stdout.read() if server.stdout else ""
        traceback_seen = "Traceback" in output
        if output.strip():
            print("\n--- uvicorn output ---")
            print(output.strip())
        check("no traceback in the server output", not traceback_seen)
        if DATABASE_FILE.exists():
            DATABASE_FILE.unlink()
            print(f"removed the {DATABASE_FILE.name} created by this check")

    print("-" * 80)
    print(f"checks failed: {len(FAILURES)}")
    for failure in FAILURES:
        print(f"  - {failure}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
