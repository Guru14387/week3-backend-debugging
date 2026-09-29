# Week3 Backend Debugging API

A small but realistic **task-management backend** built for the Week 3 internship
assignment *Debugging, Testing and Error Resolution*.

The repository started as a **buggy baseline**: five defects were seeded on purpose
(one per required category) and a sixth was found while writing the baseline tests.
Every defect was reproduced with a failing test first, then fixed, then covered by a
regression test. All raw evidence is stored in [`artifacts/`](artifacts) and explained in
[`DEBUGGING_REPORT.md`](DEBUGGING_REPORT.md).

## Features

- Create, read, update (PUT + PATCH), delete tasks
- Listing with pagination (`skip`, `limit`) and the total number of matches
- Filtering by `status` and `priority`, case-insensitive substring search (`q`) across
  title **and** description, all combined with AND semantics
- Aggregated statistics endpoint (`/tasks/stats`): totals, per status, per priority,
  completion rate, overdue counter, comment counters
- Nested comments sub-resource for each task (`comment_count` is exposed on tasks)
- Centralised validation through Pydantic schemas (blank/overlong titles, unknown fields,
  invalid enums, invalid dates, timezone-aware due dates normalised to UTC)
- Clean HTTP semantics (201 on create, 204 on delete, 404 for unknown ids, 422 for
  invalid payloads) and error responses that never leak internals
- Self-contained SQLite database - no server and no credentials required

## Tech stack

| Layer | Choice | Verified version |
| --- | --- | --- |
| Language | Python | 3.14.3 (targets 3.11+) |
| Web framework | FastAPI | 0.141.1 |
| Validation | Pydantic v2 | 2.13.5 |
| ORM | SQLAlchemy 2.x | 2.0.52 |
| Database | SQLite (file for the app, in-memory for tests) | stdlib |
| Tests | pytest + `TestClient` (httpx) | 8.4.2 / 0.28.1 |
| Static checks | ruff | 0.16.8 |
| Report generation | python-docx | 1.2.0 |

## Installation

```powershell
cd week3_backend_debugging
python -m venv .venv                 # optional but recommended
.\.venv\Scripts\Activate.ps1         # Windows PowerShell
python -m pip install -r requirements.txt
```

## Running the API

```powershell
uvicorn app.main:app --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>
- Health probe: <http://127.0.0.1:8000/health>

The SQLite file (`week3_tasks.db`) is created automatically on startup. Set
`DATABASE_URL` to point somewhere else, for example:

```powershell
$env:DATABASE_URL = "sqlite:///./scratch.db"; uvicorn app.main:app
```

A scripted startup check (launches uvicorn on a free port, drives a full lifecycle over
real HTTP and shuts the server down again) is available as well:

```powershell
python scripts/smoke_check.py
```

## Running tests

```powershell
python -m pytest -v                    # full suite (102 tests)
python -m pytest -m performance -v     # SQL statement budget / latency checks
python -m pytest tests/test_regression.py -v   # one test per fixed defect
python -m pytest --collect-only -q     # test inventory only
python -m ruff check .                 # static checks
```

Every test runs against its own in-memory SQLite database, so the suite is fast,
deterministic and leaves no files behind.

## API endpoints

| Method | Path | Purpose | Success | Errors |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | Liveness probe | 200 | - |
| `POST` | `/tasks` | Create a task | **201** | 422 |
| `GET` | `/tasks` | List / filter / search tasks | 200 | 422 |
| `GET` | `/tasks/stats` | Aggregated backlog counters | 200 | - |
| `GET` | `/tasks/{task_id}` | Fetch one task | 200 | 404, 422 |
| `PUT` | `/tasks/{task_id}` | Replace a task | 200 | 404, 422 |
| `PATCH` | `/tasks/{task_id}` | Update selected fields | 200 | 404, 422 |
| `DELETE` | `/tasks/{task_id}` | Delete a task (and its comments) | 204 | 404, 422 |
| `POST` | `/tasks/{task_id}/comments` | Add a comment | 201 | 404, 422 |
| `GET` | `/tasks/{task_id}/comments` | List the comments of a task | 200 | 404, 422 |

Query parameters of `GET /tasks`: `status` (`pending` \| `in_progress` \| `completed`),
`priority` (`low` \| `medium` \| `high`), `q` (1-200 characters),
`skip` (>= 0, default 0), `limit` (1-200, default 50).

Example:

```powershell
curl.exe -X POST http://127.0.0.1:8000/tasks -H "Content-Type: application/json" `
  -d '{\"title\":\"Fix the login flow\",\"priority\":\"high\",\"due_date\":\"2026-10-05T09:30:00+02:00\"}'

curl.exe "http://127.0.0.1:8000/tasks?status=pending&priority=high&q=login"
curl.exe http://127.0.0.1:8000/tasks/stats
```

## Testing approach

| Suite | Tests | Focus |
| --- | --- | --- |
| `tests/test_crud.py` | 16 | Unit tests of the data-access layer and the Pydantic schemas |
| `tests/test_tasks.py` | 13 | Task lifecycle and the comment sub-resource |
| `tests/test_api.py` | 19 | HTTP contract, pagination, filters, search, statistics, OpenAPI |
| `tests/test_edge_cases.py` | 41 | Validation, boundaries, unknown ids, invalid query parameters |
| `tests/test_regression.py` | 8 | One test per fixed defect (`BUG-01` ... `BUG-06`) |
| `tests/test_performance.py` | 5 | SQL statement budget (N+1 guard) and a latency budget |

The performance tests count the SQL statements the application really sends by
listening to SQLAlchemy's `before_cursor_execute` event, so they assert that the number
of statements is **independent of the page size** instead of relying on flaky timings.

## Debugging summary

| ID | Category | Symptom on the baseline | Root cause | Status |
| --- | --- | --- | --- | --- |
| BUG-01 | API contract | `POST /tasks` answered `200` | route registered without `status_code=201` | fixed |
| BUG-02 | Validation | `PATCH` accepted `""`/`"   "` (title blanked) and `null` (HTTP 500) | update schema re-declared `title` without the shared validation | fixed |
| BUG-03 | Query logic | `?status=pending&priority=low` returned the union; `?q=` ignored descriptions | conditions combined with `or_`, search limited to `title` | fixed |
| BUG-04 | Error handling | unknown id answered `500` and leaked the SQLAlchemy message | `Query.one()` + blanket `except Exception` mapped everything to 500 | fixed |
| BUG-05 | Performance | 202 SQL statements for a 200 task page (N+1) | one lazy `SELECT` per row for `comment_count`, Python-side aggregation | fixed |
| BUG-06 | Validation | `due_date` with a `+02:00` offset was stored two hours off | the UTC normaliser only handled `datetime`, never the JSON string | fixed |

Measured before/after for `GET /tasks?limit=200` with 200 tasks (same machine,
same benchmark, run minutes apart):

| Metric | Baseline | Fixed |
| --- | --- | --- |
| SQL statements | 202 | 3 |
| Median latency | 70.2 ms | 13.0 ms |

`GET /tasks/stats`: 201 statements / 66.4 ms → 6 statements / 5.3 ms.
Full details, reproduction steps and the raw logs are in
[`DEBUGGING_REPORT.md`](DEBUGGING_REPORT.md) and [`artifacts/`](artifacts).

## Project structure

```
week3_backend_debugging/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI application + lifespan
│   ├── database.py           # engine, session factory, SQLite pragmas
│   ├── models.py             # Task / Comment ORM models + enums
│   ├── schemas.py            # Pydantic request/response models
│   ├── crud.py               # data-access layer
│   └── routes/
│       ├── __init__.py
│       └── tasks.py          # /tasks endpoints
├── tests/
│   ├── conftest.py
│   ├── test_crud.py
│   ├── test_tasks.py
│   ├── test_api.py
│   ├── test_edge_cases.py
│   ├── test_regression.py
│   └── test_performance.py
├── scripts/
│   ├── reproduce_bugs.py     # demonstrates every fixed defect (exit code 0 = all fixed)
│   └── smoke_check.py        # real uvicorn startup + end-to-end HTTP check
├── benchmarks/
│   └── benchmark_list_tasks.py
├── artifacts/                # raw evidence captured from real runs
│   ├── internal_bug_register.md
│   ├── baseline_*.txt
│   └── final_*.txt
├── report/
│   └── Week3_Debugging_Report.docx
├── pyproject.toml            # pytest + ruff configuration
├── requirements.txt
├── README.md
└── DEBUGGING_REPORT.md
```
