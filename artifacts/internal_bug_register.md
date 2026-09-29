# Internal bug register (baseline)

This file is the internal record of the defects that were **deliberately seeded**
into the baseline of the *Week3 Backend Debugging API*. It was written before any
fix was applied and is kept out of the application code on purpose, so that the
defects had to be located through testing and debugging instead of reading a
comment.

Nothing in this file is a fabricated result: every entry was reproduced with
`tests/`, `scripts/reproduce_bugs.py` and `benchmarks/benchmark_list_tasks.py`
before the corresponding fix was written. The raw evidence lives next to this
file:

| Artefact | Content |
| --- | --- |
| `baseline_pytest_output.txt` | full `pytest` run against the buggy baseline |
| `baseline_reproduce_bugs.txt` | per-defect observed vs expected behaviour (baseline) |
| `baseline_benchmark.txt` | measured SQL statement counts and latency (baseline) |
| `baseline_smoke_check.txt` | live `uvicorn` startup + HTTP checks (baseline) |
| `final_*.txt` | the same four runs after all fixes |

## Seeded defects

| ID | Category | File / function | Seeded defect | Intended user-visible symptom |
| --- | --- | --- | --- | --- |
| BUG-01 | Functional / API contract | `app/routes/tasks.py` → `create_task` | The route is registered without `status_code=201`, so FastAPI replies with its default `200 OK`. | `POST /tasks` answers `200` instead of `201 Created`. |
| BUG-02 | Validation / edge case | `app/schemas.py` → `TaskUpdate` | The update schema re-declares `title` as a plain `str \| None` with only `max_length`, losing the trimming / non-blank validation that `TaskCreate` has. | `PATCH /tasks/{id}` accepts `""` and `"   "` (title is blanked) and forwards `null` to the database, which raises an `IntegrityError` → HTTP 500. |
| BUG-03 | Database / query logic | `app/crud.py` → `_build_filter` | Filter conditions are combined with `or_` instead of `and_`, and the search predicate only looks at `Task.title` (the `description` column is ignored). | `?status=pending&priority=low` returns the union of both conditions; `?q=...` misses description-only matches. |
| BUG-04 | Error handling | `app/crud.py` → `get_task` + `app/routes/tasks.py` → `read_task` | `Query.one()` raises `NoResultFound` for a missing row and the surrounding `except Exception` maps every failure to `HTTP 500`, echoing the internal SQLAlchemy message to the client. | `GET /tasks/999999` answers `500 {"detail": "Unable to retrieve task 999999: No row was found …"}` instead of `404`. |
| BUG-05 | Performance bottleneck | `app/crud.py` → `to_task_read`, `get_statistics` | Comment counters are produced by iterating ORM objects and touching the lazy `Task.comments` relationship (and, for the statistics endpoint, aggregating in Python). | 1 extra `SELECT` per task: N+1 queries on `GET /tasks` and `GET /tasks/stats`; response time grows linearly with the page size. |

## Deliberately *not* broken

The following behaviours are correct in the baseline and stay correct after the
fixes (they are covered by tests so a regression cannot slip in):

* `PUT /tasks/{id}`, `PATCH /tasks/{id}`, `DELETE /tasks/{id}` and both comment
  endpoints already answer `404` for unknown identifiers (`_require_task` helper).
* Request validation of `TaskCreate`, `CommentCreate` and the query parameters
  (`limit`, `skip`, `q`, enum filters) already answers `422`.
* `extra="forbid"` on the request schemas already rejects typo fields.
* `POST /tasks/{id}/comments` already answers `201`.

## Additional defect discovered while writing the baseline tests (not seeded)

| ID | Category | File / function | Defect | Symptom |
| --- | --- | --- | --- | --- |
| BUG-06 | Validation / edge case | `app/schemas.py` → `_normalise_due_date` | The "convert the client offset to UTC" validator only inspected `datetime` instances, but JSON input always arrives as a *string*, so the validator never ran. SQLAlchemy's SQLite `DATETIME` type ignores `tzinfo` and stored the local wall-clock time unchanged. | `POST /tasks` with `due_date="2026-10-05T09:30:00+02:00"` stored `09:30` instead of `07:30` UTC - a silent two hour shift that also skews the `overdue` counter of `GET /tasks/stats`. |

Found by `tests/test_edge_cases.py::test_create_normalises_timezone_aware_due_dates`
(direct evidence: the first two "edits" committed for it are in the baseline git history)
and fixed right after BUG-04, with `tests/test_regression.py::test_bug_06_*` as the guard.

## Test corrections (the application behaviour was kept)

`tests/test_api.py::test_post_task_returns_201_and_the_stored_resource` originally
asserted `created_at == updated_at`. Both columns use a Python-side default that is
evaluated twice, so the two values can differ by one microsecond on insert. The
assertion was corrected to `created_at <= updated_at`; the application behaviour is
correct and was **not** changed.
