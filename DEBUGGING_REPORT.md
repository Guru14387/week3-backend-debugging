# Debugging, Testing and Error Resolution Report

**Project:** Week3 Backend Debugging API
**Scope:** Week 3 internship assignment — find, reproduce, fix and lock down defects in an
existing backend API
**Repository root:** `week3_backend_debugging/`

Every figure, log line and code snippet quoted in this report was produced by actually
running the code in this repository. The raw evidence is stored next to this document in
[`artifacts/`](artifacts); nothing was reconstructed from memory or estimated.

---

## 1. Project Overview

The project is a self-contained task-management backend written in Python with FastAPI,
Pydantic v2, SQLAlchemy 2 and SQLite. It offers full CRUD for tasks, pagination, filtering
and search, an aggregated statistics endpoint and a nested comments sub-resource.

The repository started as a **buggy baseline**. Six defects were in scope:

| ID | Category (as required by the assignment) | One-line summary |
| --- | --- | --- |
| BUG-01 | Functional / API bug | `POST /tasks` answered `200 OK` instead of `201 Created` |
| BUG-02 | Validation / edge-case bug | `PATCH` accepted blank, whitespace-only and `null` titles |
| BUG-03 | Database / query bug | Combined filters were OR-ed and the search ignored `description` |
| BUG-04 | Error-handling bug | Unknown task id answered `500` and leaked the SQLAlchemy message |
| BUG-05 | Performance bottleneck | N+1 queries on `GET /tasks` and `GET /tasks/stats` |
| BUG-06 | Validation / edge-case bug | A `due_date` with a UTC offset was stored two hours off (found during Phase 2) |

BUG-01 … BUG-05 were seeded deliberately into the baseline (record:
[`artifacts/internal_bug_register.md`](artifacts/internal_bug_register.md)). BUG-06 was not
planted — it surfaced when the first baseline test run executed
`tests/test_edge_cases.py::test_create_normalises_timezone_aware_due_dates`, and its
failing run is preserved in the baseline evidence files.

## 2. Objective

1. Build a realistic backend with intentionally inserted, junior-developer-grade defects.
2. Prove every defect exists by running the code (tests, a reproduction script, a live
   HTTP smoke check and a benchmark) instead of reading the source.
3. Identify the root cause of each defect.
4. Fix each defect with the smallest clean production-quality change.
5. Add unit, integration, edge-case, regression and performance tests so that none of the
   defects can come back.
6. Document the work factually, including the raw logs.

## 3. Development Environment

| Item | Value |
| --- | --- |
| Operating system | Windows (win32) |
| Python | 3.14.3 (`C:\Program Files\Python314\python.exe`) |
| FastAPI | 0.141.1 (Starlette 1.6.0) |
| Pydantic | 2.13.5 |
| SQLAlchemy | 2.0.52 |
| pytest | 8.4.2 (pluggy 1.6.0) |
| HTTP client for tests | httpx 0.28.1 through `starlette.testclient.TestClient` |
| uvicorn | 0.52.4 |
| ruff | 0.16.8 |
| python-docx | 1.2.0 (generates `report/Week3_Debugging_Report.docx`) |
| Database | SQLite — file database for the app, in-memory (`sqlite://`) for tests |
| Version control | git 2.55.0 — baseline and each fix are separate commits |

Environment notes actually observed while running:

* `fastapi/testclient.py` emits `StarletteDeprecationWarning: Using httpx with
  starlette.testclient is deprecated; install httpx2 instead.` and Starlette itself emits a
  `DeprecationWarning` about the `anyio.abc.BlockingPortal` alias. Both are library
  deprecations in Starlette 1.6.0, they do not affect behaviour, and pytest reports exactly
  two warnings in every run. They were deliberately **not** silenced so the report stays
  honest.
* The test suite never touches the file database: the `client` fixture is not used as a
  context manager, so the application lifespan (and therefore `init_db()`) does not run
  while testing.

## 4. Initial Problems Identified

The baseline had a complete test suite written from the specification plus two diagnostic
tools. Running them produced the following facts:

```text
# baseline, captured with:  python -m pytest -v > artifacts/baseline_pytest_output.txt
collected 100 items
30 failed, 70 passed, 2 warnings in 6.22s
```

```text
# the same final 102-test suite executed against the baseline code
# (git worktree at the baseline commit, tests/ copied from the fixed revision)
# captured in artifacts/baseline_pytest_with_final_suite.txt
31 failed, 71 passed, 2 warnings in 4.56s
```

```text
# baseline, captured with:  python scripts/reproduce_bugs.py
BUG-01  ... -> DEFECT REPRODUCED / FAIL   observed: POST /tasks -> HTTP 200
BUG-02  ... -> DEFECT REPRODUCED / FAIL   observed: PATCH title='' -> HTTP 200,
                                                     PATCH title=null -> HTTP 500,
                                                     stored title=''
BUG-03  ... -> DEFECT REPRODUCED / FAIL   observed: status=pending&priority=low -> 20 tasks,
                                                     q=burndown -> 0 tasks
BUG-04  ... -> DEFECT REPRODUCED / FAIL   observed: GET /tasks/987654 -> HTTP 500
                                                     {"detail":"Unable to retrieve task 987654:
                                                      No row was found when one was required"}
BUG-05  ... -> DEFECT REPRODUCED / FAIL   observed: limit=1 -> 3 statements,
                                                     limit=30 -> 32 statements,
                                                     stats -> 31 statements
checks: 5   passed: 0   failed: 5
```

```text
# baseline live server check, captured with: python scripts/smoke_check.py
[PASS] uvicorn started and /health answered
[FAIL] POST /tasks answers 201 -> HTTP 200
[FAIL] GET /tasks/{id} answers 404 once deleted -> HTTP 500 {...}
[FAIL] GET /tasks/987654 answers a clean 404 -> HTTP 500 {...}
checks failed: 3
```

The 31 failing tests group into exactly six root causes — the six defects listed above —
which is why no seventh cause had to be chased. Each one is analysed below.

---

## 5. Bug #1 — `POST /tasks` answered `200 OK` instead of `201 Created`

* **Description.** Creating a resource is documented (and expected by every REST client) to
  answer `201 Created`. The endpoint answered `200 OK`.
* **Observed behaviour.** `POST /tasks` → `HTTP 200`. Baseline evidence:
  `artifacts/baseline_reproduce_bugs.txt`, `artifacts/baseline_smoke_check.txt`.
* **Expected behaviour.** `POST /tasks` → `HTTP 201 Created`, with `201` documented in the
  OpenAPI operation.
* **How it was reproduced.** `python scripts/reproduce_bugs.py` (BUG-01 check) plus seven
  failing tests, e.g.
  `tests/test_regression.py::test_bug_01_post_tasks_answers_201_created` and
  `tests/test_api.py::test_post_task_returns_201_and_the_stored_resource`
  (`assert 200 == 201`).
* **Root cause.** `app/routes/tasks.py` registered the handler with
  `@router.post("", response_model=schemas.TaskRead, ...)`. FastAPI's default
  `status_code` is `200`, so the response code was never set.
* **Affected file / function.** `app/routes/tasks.py` → `create_task`.
* **Fix strategy.** Declare `status_code=status.HTTP_201_CREATED` on the route decorator —
  the smallest possible change, no other behaviour touched.
* **Applied change.**

  ```python
  @router.post(
      "",
      response_model=schemas.TaskRead,
      status_code=status.HTTP_201_CREATED,
      summary="Create a task",
  )
  ```
* **Verification.** `python scripts/reproduce_bugs.py` → `BUG-01 ... FIXED / PASS`
  (`observed: POST /tasks -> HTTP 201`); the live smoke check now reports
  `[PASS] POST /tasks answers 201 -> HTTP 201`; every related test passes.
  Commit: `fix(BUG-01)`.

---

## 6. Bug #2 — `PATCH` accepted blank, whitespace-only and `null` titles

* **Description.** `TaskCreate` validated and trimmed the title, but `TaskUpdate`
  re-declared `title` as a plain `str | None` with only `max_length`, so the update path
  lost all of that protection.
* **Observed behaviour.** `PATCH /tasks/{id}` with `{"title": ""}` → `HTTP 200` and the
  stored title became `''`; with `{"title": "   "}` → `HTTP 200` and the stored title became
  three spaces; with `{"title": null}` → `HTTP 500` (`NOT NULL constraint failed`).
  Baseline evidence: `artifacts/baseline_reproduce_bugs.txt` →
  `PATCH title='' -> HTTP 200, PATCH title=null -> HTTP 500, stored title=''`.
* **Expected behaviour.** All three payloads are rejected with `422` and the stored title
  stays unchanged; a padded title is trimmed exactly like on creation.
* **How it was reproduced.** `python scripts/reproduce_bugs.py` (BUG-02 check) and the
  failing tests `tests/test_edge_cases.py::test_patch_rejects_blank_titles[...]`,
  `::test_patch_trims_the_title`, `::test_patch_rejects_a_null_title`,
  `tests/test_tasks.py::test_patch_rejects_null_title` (`assert 500 == 422`) and
  `tests/test_crud.py::test_task_update_schema_rejects_blank_title`.
* **Root cause.** The shared, validated `Title` annotation
  (`Annotated[str, BeforeValidator(_validate_title)]`) was only used on `TaskCreate`.
  `TaskUpdate` declared its own unvalidated field, and `crud.update_task` copies every
  *provided* value into the ORM object — including `None`, which SQLite refuses because the
  column is `NOT NULL`.
* **Affected file / function.** `app/schemas.py` → `TaskUpdate.title`; consumed by
  `app/crud.py` → `update_task`.
* **Fix strategy.** Reuse the existing `Title` annotation on the update schema (trimming,
  blank rejection and the 200 character limit come for free) and add a small
  `field_validator` that rejects an explicitly supplied `null` before it can reach the
  database.
* **Applied change.**

  ```python
  class TaskUpdate(APIModel):
      title: Title | None = None
      ...

      @field_validator("title", mode="before")
      @classmethod
      def _reject_null_title(cls, value: object) -> object:
          """``null`` would violate the NOT NULL constraint, so reject it early."""
          if value is None:
              raise ValueError("title cannot be null - omit the field to keep the current title")
          return value
  ```

  Omitting the field still means "keep the current title" (`PATCH {}` is a no-op), because
  Pydantic does not run field validators for fields that were not sent.
* **Verification.** `BUG-02 ... FIXED / PASS` with
  `PATCH title='' -> HTTP 422, PATCH title=null -> HTTP 422, stored title='Protected title'`;
  `PATCH {"title": "  after  "}` stores `after`. Commit: `fix(BUG-02)`.

---

## 7. Bug #3 — Combined filters behaved like OR and search ignored the description

* **Description.** `GET /tasks` supports `status`, `priority` and `q`. Multiple filters are
  supposed to narrow the result set (AND). The baseline unioned them (OR), and `q` only
  looked at `Task.title`, so a term that only occurs in the description was never found.
* **Observed behaviour.** With 30 seeded tasks (`status` cycles every 3 rows, `priority`
  every 2 rows, the phrase "mentions the burndown chart" appears in every fifth
  description):
  `?status=pending&priority=low` → **20** tasks (expected 5) and `?q=burndown` → **0** tasks
  (expected 6). Baseline evidence: `artifacts/baseline_reproduce_bugs.txt`.
  At test level: `assert 3 == 1` (`tests/test_api.py::test_filters_are_combined_with_and`)
  and `assert 0 == 1` (`::test_search_matches_the_description`).
* **Expected behaviour.** `?status=pending&priority=low` returns only rows that satisfy
  *both* conditions (5 of 30) and `?q=burndown` finds rows where the term occurs in the
  title **or** in the description (6 of 30). All three parameters together must intersect.
* **How it was reproduced.** `python scripts/reproduce_bugs.py` (BUG-03 check) and the
  failing tests `tests/test_api.py::test_filters_are_combined_with_and`,
  `::test_search_matches_the_description`, `::test_search_combines_with_the_other_filters`,
  `tests/test_crud.py::test_list_tasks_combines_filters_with_and`,
  `::test_list_tasks_search_covers_title_and_description` and
  `tests/test_regression.py::test_bug_03_*`.
* **Root cause.** In `app/crud.py` → `_build_filter` the individual conditions were
  collected in a list and combined with `return or_(*conditions)`, and the search condition
  was built as `models.Task.title.like(f"%{q}%")` — title only. `crud.list_tasks` then
  applied that single clause in one `.filter(...)` call, so the OR semantics were baked in.
* **Affected file / function.** `app/crud.py` → `_build_filter`, used by `list_tasks`
  (`GET /tasks`).
* **Fix strategy.** Combine the independent conditions with `and_` and keep `or_` only
  *inside* the search condition, where it is correct (title OR description). Use `ilike`
  so the search stays case-insensitive and covers both text columns.
* **Applied change.**

  ```python
  conditions = []
  if status is not None:
      conditions.append(models.Task.status == _as_column_value(status))
  if priority is not None:
      conditions.append(models.Task.priority == _as_column_value(priority))
  if q:
      pattern = f"%{q}%"
      conditions.append(
          or_(
              models.Task.title.ilike(pattern),
              models.Task.description.ilike(pattern),
          )
      )
  if not conditions:
      return None
  return and_(*conditions)
  ```
* **Verification.** `BUG-03 ... FIXED / PASS` with
  `status=pending&priority=low -> 5 tasks, q=burndown -> 6 tasks`; the pagination totals are
  now correct as well (`total` is computed from the same clause). Commit: `fix(BUG-03)`.

---

## 8. Bug #4 — Unknown task id answered `500` and leaked the internal error

* **Description.** Requesting a task that does not exist is an ordinary client error and
  must answer `404`. The baseline answered `500 Internal Server Error` and echoed the
  SQLAlchemy exception text to the caller.
* **Observed behaviour.**
  `GET /tasks/987654` → `500 {"detail":"Unable to retrieve task 987654: No row was found
  when one was required"}` (baseline `artifacts/baseline_reproduce_bugs.txt` and
  `artifacts/baseline_smoke_check.txt`). The body disclosed internals: the SQLAlchemy
  message, the internal phrasing and the fact that a bare `.one()` lookup was used.
* **Expected behaviour.** `404` with the same body the other endpoints produce:
  `{"detail": "Task 987654 not found"}` and no internal detail whatsoever.
* **How it was reproduced.** `python scripts/reproduce_bugs.py` (BUG-04 check), the
  baseline live server check (`[FAIL] GET /tasks/987654 answers a clean 404 -> HTTP 500`),
  and the failing tests
  `tests/test_edge_cases.py::test_unknown_task_id_returns_404_not_500`,
  `::test_error_responses_do_not_leak_internal_details`,
  `tests/test_tasks.py::test_mutating_and_reading_unknown_tasks_returns_404[get-/tasks/424242]`
  (`assert 500 == 404`) and `tests/test_regression.py::test_bug_04_*`.
* **Root cause.** Two mistakes reinforcing each other inside
  `app/routes/tasks.py` → `read_task`:
  1. `crud.get_task()` used `Query.one()`, which raises `sqlalchemy.exc.NoResultFound`
     instead of returning `None` when no row matches;
  2. the route wrapped the lookup in `try/except Exception` and translated *every*
     exception into `HTTPException(500, detail=f"Unable to retrieve task {task_id}: {exc}")`,
     so a `404` branch was unreachable and the exception text became the response body.
* **Affected file / function.** `app/crud.py` → `get_task` (wrong accessor) and
  `app/routes/tasks.py` → `read_task` (blanket handler).
* **Fix strategy.** Remove the blanket handler and the `.one()` accessor; reuse the existing
  `_require_task` helper that PUT/PATCH/DELETE already use, which is based on
  `Query.one_or_none()` and raises `HTTPException(404, "Task {id} not found")`. That helper
  was already correct, so the fix keeps a single code path for "fetch or 404" instead of
  adding a second one.
* **Applied change.**

  ```python
  @router.get("/{task_id}", response_model=schemas.TaskRead, summary="Get one task")
  def read_task(task_id: int, db: Session = Depends(get_db)) -> schemas.TaskRead:
      """Return a single task; answers ``404`` when the identifier is unknown."""
      task = _require_task(db, task_id)
      return crud.to_task_read(db, task)
  ```

  `crud.get_task` was deleted and `crud.get_task_or_none` now documents why
  `one_or_none()` is used.
* **Verification.** `BUG-04 ... FIXED / PASS`; the live smoke check reports
  `[PASS] GET /tasks/{id} answers 404 once deleted -> HTTP 404 {"detail":"Task 1 not found"}`
  and `[PASS] GET /tasks/987654 answers a clean 404`. Commit: `fix(BUG-04)`.

---

## 9. Bug #5 — N+1 queries on the read endpoints

* **Description.** The number of SQL statements needed for a single request grew linearly
  with the number of tasks on the page (classic N+1). The task list needed one extra
  `SELECT` per task to count comments, and the statistics endpoint re-implemented all of its
  aggregation in Python while touching `Task.comments` row by row.
* **Observed behaviour.** Measured with the SQLAlchemy `before_cursor_execute` event (see
  `benchmarks/benchmark_list_tasks.py`), 200 tasks with one comment each:

  | Request (baseline) | SQL statements | median latency |
  | --- | --- | --- |
  | `GET /tasks?limit=200` | **202** | 70.2 ms |
  | `GET /tasks/stats` | **201** | 66.4 ms |
  | `GET /tasks/1` | 2 | 7.4 ms |

  and from the reproduction script (30 tasks): `limit=1 -> 3 statements,
  limit=30 -> 32 statements, stats -> 31 statements`. The page size changed the statement
  count by exactly the number of rows. Baseline evidence:
  `artifacts/baseline_reproduce_bugs.txt`, `artifacts/baseline_benchmark.txt`,
  `artifacts/baseline_benchmark_same_conditions.txt`.
* **Expected behaviour.** The number of statements must be a small constant that does not
  depend on how many rows are returned.
* **How it was reproduced.** The failing tests
  `tests/test_performance.py::test_list_statement_count_does_not_grow_with_the_page`
  (`assert 3 == 23` for a 25 row page),
  `::test_statistics_statement_count_is_constant`,
  `tests/test_regression.py::test_bug_05_read_endpoints_do_not_issue_one_query_per_row`, and
  the standalone benchmark.
* **Root cause.**
  * `app/crud.py` → `to_task_read` built the response with `len(task.comments)`. The
    `lazy="select"` relationship therefore fired one `SELECT` per task, and the list route
    called it once per row (`[crud.to_task_read(db, task) for task in items]`).
  * `app/crud.py` → `get_statistics` loaded `db.query(models.Task).all()` and computed every
    counter in a Python loop, including `len(task.comments)` per task.
* **Affected file / function.** `app/crud.py` → `to_task_read` (used by `GET /tasks` and by
  every single-task response) and `get_statistics` (`GET /tasks/stats`).
* **Fix strategy.** Let the database do the aggregation:
  * a new `count_comments_by_task()` runs one grouped `COUNT` query for all task ids of the
    page (`WHERE task_id IN (...) GROUP BY task_id`);
  * `to_task_reads()` uses that single query for a whole page and `to_task_read()` delegates
    to it for a single task;
  * `get_statistics()` now uses `COUNT`, `GROUP BY status`, `GROUP BY priority` and a
    filtered `COUNT` for the overdue counter.

  The list route calls `crud.to_task_reads(db, items)` once instead of looping.
* **Applied change.**

  ```python
  def count_comments_by_task(db: Session, task_ids: Sequence[int]) -> dict[int, int]:
      if not task_ids:
          return {}
      rows = (
          db.query(models.Comment.task_id, func.count(models.Comment.id))
          .filter(models.Comment.task_id.in_(list(task_ids)))
          .group_by(models.Comment.task_id)
          .all()
      )
      return dict(rows)
  ```
* **Verification.** `BUG-05 ... FIXED / PASS` with
  `limit=1 -> 3 statements, limit=30 -> 3 statements, stats -> 6 statements`. The returned
  data is unchanged: `GET /tasks` still reports `total=200` with `comment_count=1` for the
  first item, and `/tasks/stats` returns exactly the same payload as before
  (`total_comments=200`, `by_status={'pending': 67, 'in_progress': 67, 'completed': 66}`).
  Commit: `fix(BUG-05)`; locked down by `tests/test_performance.py`.

---

## 10. Bug #6 — Due date offsets were silently dropped

* **Description.** A `due_date` sent with a UTC offset (`+02:00`) denotes a specific instant.
  The API stored the local wall-clock digits instead and thereby shifted that instant. This
  defect was **not** planted; it appeared during the first baseline test run and is included
  because it is a genuine bug the test suite caught.
* **Observed behaviour.** Baseline failure (present in both baseline runs):

  ```text
  test_create_normalises_timezone_aware_due_dates:
      assert '2026-10-05T09:30:00' == '2026-10-05T07:30:00'
  ```

  `POST /tasks {"due_date": "2026-10-05T09:30:00+02:00"}` stored and returned
  `2026-10-05T09:30:00`, two hours later than the instant the client meant. The same offset
  error also skewed the `overdue` counter of `GET /tasks/stats`.
* **Expected behaviour.** The instant is preserved: `09:30+02:00` is stored and returned as
  `07:30` UTC. The application stores naive UTC timestamps on purpose, because SQLite cannot
  keep a timezone.
* **How it was reproduced.**
  `tests/test_edge_cases.py::test_create_normalises_timezone_aware_due_dates` in the
  baseline runs (`artifacts/baseline_pytest_output.txt`,
  `artifacts/baseline_pytest_with_final_suite.txt`) and
  `tests/test_regression.py::test_bug_06_due_dates_with_an_offset_are_converted_to_utc`.
* **Root cause.** In `app/schemas.py` → `_normalise_due_date` the conversion was guarded by
  `isinstance(value, datetime)`. A JSON request body always delivers the value as a
  **string**, so the guard never matched and the offset was never converted. Pydantic then
  parsed the string into a timezone-aware `datetime`, and SQLAlchemy's SQLite `DATETIME` type
  ignores `tzinfo` completely, storing `09:30` unchanged.
* **Affected file / function.** `app/schemas.py` → `_normalise_due_date`, used by the
  `DueDate` annotation on `TaskCreate` and `TaskUpdate`.
* **Fix strategy.** Parse the incoming string first (leaving anything unparsable to Pydantic,
  so a genuinely invalid date still produces a clean `422`) and then apply the existing
  aware → naive UTC conversion.
* **Applied change.**

  ```python
  if isinstance(value, str):
      try:
          value = datetime.fromisoformat(value)
      except ValueError:
          return value  # let the regular "invalid date" validation report it
  if isinstance(value, datetime) and value.tzinfo is not None:
      return value.astimezone(UTC).replace(tzinfo=None)
  return value
  ```
* **Verification.**
  `tests/test_regression.py::test_bug_06_due_dates_with_an_offset_are_converted_to_utc`
  passes (`due_date` is returned and re-read as `2026-10-05T07:30:00`) and
  `::test_bug_06_invalid_due_dates_are_still_rejected` keeps the `422` behaviour. A
  timezone-naive value (`2026-10-05T09:30:00`) is still stored unchanged. Commit:
  `fix(BUG-06)`.

### Test correction made during the baseline run

`tests/test_api.py::test_post_task_returns_201_and_the_stored_resource` failed on
`assert body["created_at"] == body["updated_at"]`
(`'...614630' == '...614640'`). Both columns use a Python-side default that is evaluated
twice, so a microsecond difference on insert is normal and correct. The assertion was
corrected to `created_at <= updated_at`; the **application behaviour was not changed**. It is
documented here so the change in the test file is not mistaken for a fix.

---

## 11. Testing Strategy

The suite is layered so that a failure immediately tells which layer broke, and every
defect gets a test at the lowest level that can catch it:

| Layer | File | Tests | Purpose |
| --- | --- | --- | --- |
| Unit | `tests/test_crud.py` | 16 | `app.crud` functions and Pydantic schemas against a real (in-memory) database |
| Resource behaviour | `tests/test_tasks.py` | 13 | task lifecycle, update semantics, comment sub-resource, cascade delete |
| Integration | `tests/test_api.py` | 19 | HTTP contract, pagination, filters, search, statistics, OpenAPI document |
| Edge cases | `tests/test_edge_cases.py` | 41 | validation, boundaries, unknown ids, invalid query parameters, unicode |
| Regression | `tests/test_regression.py` | 8 | one test per fixed defect (`BUG-01` … `BUG-06`) |
| Performance | `tests/test_performance.py` | 5 | SQL statement budget (N+1 guard) and a latency budget |
| **Total** | | **102** | |

Design decisions that keep the suite trustworthy:

* **Isolation.** `tests/conftest.py` creates one in-memory SQLite database per test
  (`StaticPool`, `sqlite://`) and overrides the `get_db` dependency, so tests never touch
  `week3_tasks.db` and cannot influence each other. Test order does not matter.
* **Real database, real SQL.** Assertions run against SQLAlchemy with SQLite, not against
  mocks, so an incorrect query (BUG-03) or an N+1 pattern (BUG-05) actually shows up.
* **Honest error semantics.** The `client` fixture is created with
  `raise_server_exceptions=False`, so an unhandled server error surfaces as a real
  `HTTP 500` response instead of an exception inside the test — that is what a client sees,
  and it is how BUG-04 was pinned down.
* **Seeding independent of the API.** The `make_task` / `make_comment` fixtures insert rows
  through the ORM, so a defect in `POST /tasks` cannot corrupt the setup of an unrelated
  test.
* **Deterministic performance checks.** Query counting uses SQLAlchemy's
  `before_cursor_execute` event instead of timing, so the N+1 guard cannot go flaky on a busy
  machine.

## 12. Unit Testing

`tests/test_crud.py` exercises the data-access layer directly:

* defaults and trimming on create (`status=pending`, `priority=medium`, padded title trimmed);
* `get_task_or_none()` for an existing row and for an unknown id;
* filter semantics (`status` AND `priority`) and search coverage (title *and* description) —
  the unit-level regression for BUG-03;
* pagination (`skip`/`limit`) with a `total` that ignores the page;
* `to_task_read()` reporting the correct `comment_count`;
* partial update versus full replace semantics;
* delete cascading to comments;
* statistics over a known dataset (totals, per status, per priority, completion rate,
  overdue, comment counters) and the empty-database case;
* schema-level validation: blank, whitespace-only and overlong titles are rejected by both
  `TaskCreate` and `TaskUpdate`.

## 13. Integration Testing

`tests/test_api.py` and `tests/test_tasks.py` drive the real ASGI application through
`TestClient`:

* `POST /tasks` → `201` with the full documented payload (BUG-01);
* `GET /tasks/{id}` → `200` with the exact field set (`id, title, description, status,
  priority, due_date, created_at, updated_at, comment_count`);
* `GET /tasks` → pagination (`skip`, `limit`), ordering by id, correct `total`;
* filtering by `status`, by `priority`, the AND combination of both, plus search on title,
  on description, case-insensitivity, search combined with filters and the no-match case
  (BUG-03);
* `PUT` (full replace; omitted fields reset to defaults) and `PATCH` (partial; untouched
  fields preserved; `{}` is a no-op; `{"title": null}` is rejected);
* `DELETE` → `204` with an empty body, then `404` on the next read;
* comment sub-resource: `201` on create, ordered listing, `comment_count` on the task and in
  the list, cascade delete;
* `GET /tasks/stats` against a known dataset and on an empty database;
* `GET /health` and the OpenAPI document (all five paths and their methods);
* unknown ids for `GET`/`PUT`/`PATCH`/`DELETE` and for the comment endpoints → `404`;
* invalid input → `422`: blank/overlong title, missing title, unknown field
  (`extra_forbidden`), invalid enum value, invalid date, `limit=0`, `limit=201`, `skip=-1`,
  empty `q`, non-integer path id.

## 14. Regression Testing

`tests/test_regression.py` contains one test per defect and names the defect in the
docstring, so the link to this report is explicit:

| Test | Defect it prevents from returning |
| --- | --- |
| `test_bug_01_post_tasks_answers_201_created` | `200` instead of `201` on create (also asserts `201` is the documented response) |
| `test_bug_02_update_payload_validates_the_title` | blank, whitespace-only, `null` and overlong titles on `PATCH` (also asserts the stored value is untouched) |
| `test_bug_02_update_also_trims_the_title` | missing trimming on the update path |
| `test_bug_03_filters_are_intersected_and_search_covers_the_description` | OR-ed filters and title-only search |
| `test_bug_04_unknown_task_returns_a_clean_404` | `500` plus leaked internals for an unknown id |
| `test_bug_05_read_endpoints_do_not_issue_one_query_per_row` | the N+1 pattern (statement count must not grow with the page size) |
| `test_bug_06_due_dates_with_an_offset_are_converted_to_utc` | silently shifted due dates |
| `test_bug_06_invalid_due_dates_are_still_rejected` | the new parsing must not swallow real validation errors |

Two of them are deliberately written as *invariants* rather than as examples: "the number of
SQL statements for `limit=1` equals the number for `limit=25`" and "the stored title is
unchanged after a rejected update". Invariants catch variations of a defect, not only the
exact payload that was originally used.

## 15. Performance Testing

The bottleneck (BUG-05) is verified in two independent ways.

**(a) Query counting inside pytest** — `tests/test_performance.py` (5 tests) listens to
SQLAlchemy's `before_cursor_execute` event on the test engine and asserts:

* `GET /tasks`: the statement count for `limit=5` equals the count for `limit=40`
  (measured: 3 and 3) and stays `<= 6`;
* `GET /tasks/stats`: the count does not grow from a 5 task backlog to a 40 task backlog
  (measured: 6 and 6) and stays `<= 8`;
* correctness is asserted at the same time: every returned row reports the right
  `comment_count` (`2` for seeded comment rows);
* latency budget: `GET /tasks?limit=200` over 200 tasks with comments stays below 1 s
  (measured median in this environment: see section 16).

**(b) Standalone benchmark** — `benchmarks/benchmark_list_tasks.py` reports the statement
count *and* the wall-clock latency of `GET /tasks`, `GET /tasks/stats` and `GET /tasks/{id}`
for a configurable dataset:

```powershell
python benchmarks\benchmark_list_tasks.py --tasks 200 --comments 1
```

The baseline numbers were captured twice: once when the buggy code was the working tree
(`artifacts/baseline_benchmark.txt`) and once more right next to the fixed measurement from a
git worktree checked out at the baseline commit
(`artifacts/baseline_benchmark_same_conditions.txt`), so the comparison cannot be blamed on a
different machine state. The single-task endpoint is included as a control: it never had an
N+1 problem, and its numbers are indeed unchanged.

## 16. Before/After Observations

All numbers below were measured with `benchmarks/benchmark_list_tasks.py --tasks 200
--comments 1` (in-memory SQLite, 5 timed repetitions, median reported). The "baseline"
column of the first table comes from a worktree checked out at the baseline commit and run
immediately before the fixed measurement, so both sides ran on the same machine state in the
same session (`artifacts/baseline_benchmark_same_conditions.txt`,
`artifacts/final_benchmark.txt`).

**Query counts and latency, 200 tasks with one comment each**

| Request | SQL statements (baseline → fixed) | Median latency (baseline → fixed) |
| --- | --- | --- |
| `GET /tasks?limit=200` | 202 → **3** (−98.5 %) | 70.2 ms → **13.0 ms** (−81 %) |
| `GET /tasks/stats` | 201 → **6** (−97.0 %) | 66.4 ms → **5.3 ms** (−92 %) |
| `GET /tasks/1` (control) | 2 → 2 (unchanged) | 7.4 ms → 6.1 ms (unchanged) |

The independent measurement inside pytest (`python -m pytest -m performance -v -s`, 200
seeded tasks with comments) reports a median of **23.3 ms** (min 20.2 ms / max 52.0 ms) for
`GET /tasks?limit=200` on the fixed revision. That figure is higher than the benchmark's
13.0 ms because it includes the pytest/TestClient overhead of that specific test and was
taken while other tests were running; the absolute latency of a request on this machine also
fluctuates between runs (the per-run min/max spread is recorded in `artifacts/`). The
deterministic metric — the number of SQL statements — is stable across all runs: 3 for the
list, 6 for the statistics, 2 for a single task.

The earlier baseline run of the same benchmark, taken while the buggy revision was still the
working tree, produced the same statement counts (202 / 201 / 2) with medians of 49.8 ms,
46.9 ms and 3.3 ms (`artifacts/baseline_benchmark.txt`). The statement counts therefore
reproduce exactly; the latency values vary with machine load, which is why the report states
both runs.

**Behaviour before/after**

| Observation | Baseline | Fixed |
| --- | --- | --- |
| `POST /tasks` | `HTTP 200` | `HTTP 201` |
| `PATCH` with `{"title": ""}` | `HTTP 200`, stored title becomes `''` | `HTTP 422`, stored title unchanged |
| `PATCH` with `{"title": "   "}` | `HTTP 200`, stored title becomes 3 spaces | `HTTP 422`, stored title unchanged |
| `PATCH` with `{"title": null}` | `HTTP 500` (NOT NULL violation) | `HTTP 422` |
| `GET /tasks/987654` | `HTTP 500` + leaked SQLAlchemy message | `HTTP 404` `{"detail":"Task 987654 not found"}` |
| `GET /tasks?status=pending&priority=low` (30 seeded tasks) | 20 tasks (union) | 5 tasks (intersection) |
| `GET /tasks?q=burndown` (30 seeded tasks) | 0 tasks | 6 tasks |
| `POST /tasks` with `due_date = 2026-10-05T09:30:00+02:00` | stored as `09:30` | stored as `07:30` UTC |
| SQL statements for `GET /tasks?limit=30` (30 seeded tasks) | 32 | 3 |
| SQL statements for `GET /tasks/stats` (30 seeded tasks) | 31 | 6 |

Everything that was already correct stayed correct: `PUT`/`PATCH`/`DELETE` still answer
`404` for unknown ids, `POST /tasks/{id}/comments` still answers `201`, validation still
answers `422`, and the statistics payload is byte-for-byte identical before and after the
performance work.

## 17. Final Test Results

Commands executed in the project root (`week3_backend_debugging/`) and their real output:

| # | Command | Result | Evidence file |
| --- | --- | --- | --- |
| 1 | `python -m pytest -q` | `102 passed, 2 warnings in 1.74s` | `artifacts/final_pytest_output.txt` |
| 2 | `python -m pytest -v` | same 102 tests, all `PASSED` | `artifacts/final_pytest_output.txt` (baseline counterpart: `baseline_pytest_output.txt`) |
| 3 | `python -m pytest -m performance -v -s` | `5 passed, 97 deselected` | `artifacts/final_performance_tests.txt` |
| 4 | `python -m pytest tests/test_regression.py -v` | `8 passed` | `artifacts/final_regression_tests.txt` |
| 5 | `python -m ruff check .` | `All checks passed!` | `artifacts/final_ruff_check.txt` |
| 6 | `python scripts/reproduce_bugs.py` | `checks: 5 passed: 5 failed: 0` (exit code 0) | `artifacts/final_reproduce_bugs.txt` |
| 7 | `python scripts/smoke_check.py` | `checks failed: 0` (11 checks over real HTTP) | `artifacts/final_smoke_check.txt` |
| 8 | `python scripts/startup_check.py` | `checks failed: 0` (uvicorn + default file database) | `artifacts/final_app_startup_check.txt` |
| 9 | `python benchmarks/benchmark_list_tasks.py --tasks 200 --comments 1` | `3` statements, `N+1 pattern detected: NO` | `artifacts/final_benchmark.txt` |

Notes on the two warnings: they are the deprecation notices of Starlette 1.6.0 described in
section 3, not test failures. `--strict-markers` and `--strict-config` are enabled in
`pyproject.toml`, so an unknown marker or option would have failed the run.

Status of the application itself: uvicorn starts with both the default file database and an
environment-provided database, `week3_tasks.db` is created by the startup hook, `/health`
answers `{"status": "ok", "service": "Week3 Backend Debugging API", "version": "1.0.0"}`,
the OpenAPI document lists all five paths, and every endpoint was exercised over real HTTP
(create → read → patch → comment → filter → statistics → delete → 404). Nothing is left
failing.

## 18. Conclusion

The assignment asked for a realistic backend, real defects, real fixes and real tests — not
for a report about them. That is what the repository contains:

* a runnable FastAPI + SQLAlchemy + SQLite service with CRUD, filtering, search, statistics
  and comments;
* five deliberately seeded defects (one per required category) plus one genuine defect that
  the tests found by themselves;
* every defect reproduced before it was touched: `30 failed, 70 passed` on the baseline, and
  `31 failed, 71 passed` when the final 102-test suite runs against the baseline code;
* a minimal, targeted fix per defect, committed separately
  (`fix(BUG-01)` … `fix(BUG-06)`), with the baseline preserved in git history;
* 102 tests that pass on the fixed revision, including eight regression tests, five
  performance tests and 41 edge-case tests, plus a lint run with no findings;
* a measurable performance improvement — 202 → 3 SQL statements and 70.2 ms → 13.0 ms for a
  200 task page, 201 → 6 statements and 66.4 ms → 5.3 ms for the statistics endpoint — with
  byte-for-byte identical payloads;
* a live-server verification (`smoke_check.py`, `startup_check.py`) that exercises the API
  over real HTTP instead of only through the test client.

Two lessons are worth keeping from the exercise. First, the highest-value tests were the
ones written before the fixes: the OR/AND filter defect, the leaked-500 defect and the
timezone defect were all invisible in a code review but trivial to catch once behaviour was
asserted. Second, the "smallest change" discipline mattered — reusing the already correct
`_require_task` helper and the already correct `Title` annotation produced smaller and
clearer diffs than writing new code would have.

Known limitations, stated honestly:

* Latency figures are single-machine observations of an in-memory SQLite database and
  therefore indicative, not a capacity statement. Query counts are the reliable metric and
  are asserted by tests.
* SQLite has no timezone support, so the API stores naive UTC timestamps by design; the
  conversion happens at the schema boundary and is covered by tests.
* `q` is a simple `LIKE` substring search without FTS indexing. For the expected data volume
  of this assignment that is appropriate, but it is the next performance topic if the dataset
  grows.

## 19. Files Changed

Fix commits (newest first) as produced by `git log --oneline`:

```text
71d5f47 fix(BUG-05): replace the N+1 comment lookups with single aggregate queries
5265ceb test: correct the created_at/updated_at assumption and record BUG-06 in the register
78170c1 fix(BUG-06): convert due date offsets to UTC instead of silently dropping them
8cc74f2 fix(BUG-04): unknown task id answers 404 instead of a leaked 500
a6f5c74 fix(BUG-03): combine list filters with AND and search title+description
f209c76 fix(BUG-02): validate the title on PATCH (blank/whitespace/null/overlong)
0d800eb fix(BUG-01): POST /tasks answers 201 Created instead of 200 OK
c9d5dcb baseline: buggy Week3 task API (5 seeded defects) + tests, scripts, benchmarks
        and baseline evidence
```

| File | Change |
| --- | --- |
| `app/routes/tasks.py` | BUG-01 (`status_code=201`), BUG-04 (`read_task` uses `_require_task`), BUG-05 (list uses `to_task_reads`) |
| `app/schemas.py` | BUG-02 (`TaskUpdate.title: Title \| None` + `_reject_null_title`), BUG-06 (offset handling in `_normalise_due_date`), lint (`UTC`) |
| `app/crud.py` | BUG-03 (`and_` + `ilike` on title/description), BUG-04 (`get_task` removed, `get_task_or_none` documented), BUG-05 (`count_comments_by_task`, `to_task_reads`, SQL aggregation in `get_statistics`), lint fix |
| `app/models.py` | lint only (`datetime.UTC`, unquoted forward reference) |
| `app/routes/__init__.py` | lint only (unused import removed) |
| `tests/conftest.py` | new: fixtures (in-memory engine, client, query log, `make_task`, `make_comment`) |
| `tests/test_crud.py` | new: 16 unit tests |
| `tests/test_tasks.py` | new: 13 resource/lifecycle tests |
| `tests/test_api.py` | new: 19 integration tests (one assertion corrected, see section 10) |
| `tests/test_edge_cases.py` | new: 41 edge-case tests |
| `tests/test_regression.py` | new: 8 regression tests, one per defect |
| `tests/test_performance.py` | new: 5 performance/query-budget tests |
| `scripts/reproduce_bugs.py` | new: demonstrates every defect (exit code 0 = all fixed) |
| `scripts/smoke_check.py` | new: uvicorn startup + full HTTP lifecycle |
| `scripts/startup_check.py` | new: startup with the default file database |
| `benchmarks/benchmark_list_tasks.py` | new: statement count + latency benchmark |
| `artifacts/internal_bug_register.md` | new: internal record of the seeded defects (written before any fix) |
| `artifacts/baseline_*.txt` | new: raw baseline evidence (pytest, reproduction, benchmark, smoke check, same-conditions rerun, final suite on baseline code) |
| `artifacts/final_*.txt` | new: raw evidence of the verified revision |
| `pyproject.toml` | new: pytest and ruff configuration |
| `requirements.txt` | new: runtime and tooling dependencies with verified versions |
| `README.md` | new: overview, installation, endpoints, testing and debugging summary |
| `DEBUGGING_REPORT.md` | new: this report |
| `report/Week3_Debugging_Report.docx` | new: internship submission report (generated with python-docx) |
