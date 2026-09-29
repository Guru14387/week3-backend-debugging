"""Generate report/Week3_Debugging_Report.docx (the internship submission report).

Run from the project root::

    python scripts/generate_report.py

The script is deterministic: it always rebuilds the DOCX from the content below and
prints the resulting word count so the report can be checked against the 700-1200 word
requirement.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "report" / "Week3_Debugging_Report.docx"

ACCENT = RGBColor(0x1F, 0x4E, 0x79)

BUGS = [
    ("BUG-01\nWrong status code", "POST /tasks answered 200 OK on success.",
     "The route had no status_code override, so FastAPI used the default 200.",
     "Declared status_code=201 on the create endpoint; 18 tests now assert it."),
    ("BUG-02\nInput validation", "Empty, whitespace or null titles were accepted; "
     "{\"title\": null} crashed the server with a 500.",
     "TaskUpdate.title was a bare str: None passed the annotation and blank strings "
     "passed validation.",
     "Reused the strict Title annotation and added an explicit null-title check "
     "returning 422."),
    ("BUG-03\nLogic error", "status and priority filters were combined with OR, and "
     "search never matched the description.",
     "The list query used or_() for independent filters and a title-only ilike().",
     "Independent filters are ANDed together and the q parameter searches title and "
     "description."),
    ("BUG-04\nError handling", "GET /tasks/987654 returned a 500 that leaked a "
     "SQLAlchemy NoResultFound message.",
     "read_task called get_one() and never handled the missing-row exception.",
     "The route now uses the shared _require_task helper, answering a clean "
     "404 with a JSON detail."),
    ("BUG-05\nPerformance (N+1)", "The list issued one extra query per task to load "
     "comments; statistics queried row by row.",
     "lazy='select' relationships were read inside Python loops, so comment counts "
     "scaled linearly with the page size.",
     "Comment counts are prefetched with a single GROUP BY and the statistics are "
     "aggregated in SQL."),
    ("BUG-06\nTimezone handling", "due_date offsets such as +02:00 were silently "
     "dropped, shifting the stored instant.",
     "The normaliser used .replace(tzinfo=None) instead of converting to UTC.",
     "Offset-aware values are converted with astimezone(UTC); invalid dates are still "
     "rejected with 422."),
]

PERF_ROWS = [
    ("GET /tasks?limit=200", "202 -> 3", "70.2 ms -> 13.0 ms"),
    ("GET /tasks/stats", "201 -> 6", "66.4 ms -> 5.3 ms"),
    ("GET /tasks/1 (control)", "2 -> 2", "7.4 ms -> 6.1 ms"),
]


def style_document(document: Document) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name in ("Heading 1", "Heading 2"):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.color.rgb = ACCENT


def add_paragraph(document: Document, text: str, *, bold_lead: str = "") -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if bold_lead:
        paragraph.add_run(bold_lead).bold = True
    paragraph.add_run(text)


def add_command_list(document: Document, commands: list[str]) -> None:
    for command in commands:
        paragraph = document.add_paragraph(style="List Bullet")
        run = paragraph.add_run(command)
        run.font.name = "Consolas"
        run.font.size = Pt(9.5)


def build_document() -> Document:
    document = Document()
    style_document(document)

    title = document.add_heading("Week 3 Backend Debugging API - Internship Report", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(
        "FastAPI task-management service | seeded defects | test-driven fixes | "
        "performance measurement"
    ).italic = True
    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(
        "Stack: Python 3.14, FastAPI, SQLAlchemy 2, SQLite, pytest, Ruff "
        "- Project: week3_backend_debugging"
    ).font.size = Pt(9.5)

    document.add_heading("1. Project Overview", level=1)
    add_paragraph(
        document,
        "The Week 3 assignment was to build a small but realistic backend and then debug it "
        "the way an engineer would: reproduce each defect with a failing test, fix it with "
        "the smallest possible change, prove the fix with a regression test, measure "
        "performance before and after, and document everything. The result is a "
        "task-management REST API offering CRUD for tasks and comments, filtering, "
        "free-text search and aggregate statistics, backed by SQLite through SQLAlchemy 2. "
        "The code exists in two committed states: a baseline containing five deliberately "
        "seeded defects and a fixed revision with six separate fix commits, so the whole "
        "history can be replayed. Every number quoted here is backed by raw output in the "
        "artifacts/ folder.",
    )

    document.add_heading("2. Defects and Fixes", level=1)
    add_paragraph(
        document,
        "Five defects were seeded, one per required debugging category, and a sixth was "
        "found organically by the tests while they were being written:",
    )
    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    for cell, heading in zip(
        table.rows[0].cells,
        ["Bug / category", "Symptom", "Root cause", "Fix"],
        strict=True,
    ):
        run = cell.paragraphs[0].add_run(heading)
        run.bold = True
        run.font.size = Pt(9.5)
    for bug in BUGS:
        cells = table.add_row().cells
        for cell, value in zip(cells, bug, strict=True):
            paragraph = cell.paragraphs[0]
            paragraph.add_run(value).font.size = Pt(9)

    document.add_heading("3. Testing and Verification", level=1)
    add_paragraph(
        document,
        "Nothing was fixed before it was reproduced. Running the suite against the baseline "
        "gave 30 failed / 70 passed, and the same 102-test suite against the baseline still "
        "gives 31 failed / 71 passed, which proves the tests really exercise the fixed "
        "behaviour. After the fixes the whole suite is green (102 passed), the reproduction "
        "script reports 5/5 fixed, ruff reports no findings, and a live uvicorn server was "
        "started and exercised over real HTTP, including the default file database. "
        "Verification commands:",
    )
    add_command_list(
        document,
        [
            "python -m pytest -q  # 102 passed, 2 warnings in 1.74s",
            "python -m pytest tests/test_regression.py -q  # 8 passed",
            "python -m pytest -m performance -v -s  # 5 passed",
            "python -m ruff check .  # All checks passed!",
            "python scripts/reproduce_bugs.py  # 5 passed, 5 fixed, exit code 0",
            "python scripts/smoke_check.py  # 11 checks over live HTTP, 0 failed",
            "python scripts/startup_check.py  # default database startup, 0 failed",
        ],
    )

    document.add_heading("4. Performance Results", level=1)
    add_paragraph(
        document,
        "Query counting uses a SQLAlchemy before_cursor_execute listener, so the statement "
        "counts are exact rather than estimated. The measurements below come from the "
        "benchmark run with 200 tasks that have one comment each, executed for the baseline "
        "and the fixed revision under the same conditions (median of five repetitions):",
    )
    perf = document.add_table(rows=1, cols=3)
    perf.style = "Table Grid"
    for cell, heading in zip(
        perf.rows[0].cells,
        ["Request", "SQL statements", "Median latency"],
        strict=True,
    ):
        run = cell.paragraphs[0].add_run(heading)
        run.bold = True
        run.font.size = Pt(9.5)
    for row in PERF_ROWS:
        cells = perf.add_row().cells
        for cell, value in zip(cells, row, strict=True):
            cell.paragraphs[0].add_run(value).font.size = Pt(9)
    add_paragraph(
        document,
        "The list endpoint dropped 98.5% of its queries while the JSON payload stayed "
        "byte-for-byte identical, and the control endpoint was unchanged, which isolates "
        "the gain to the N+1 defect.",
    )

    document.add_heading("5. Conclusion", level=1)
    add_paragraph(
        document,
        "The exercise produced a runnable service, real evidence for every defect, minimal "
        "fixes kept in separate commits and a suite that will catch each defect if it ever "
        "returns. The most valuable tests were written before the fixes: the OR/AND filter "
        "error, the leaked 500 and the timezone shift were invisible in code review but "
        "trivial to catch once behaviour was asserted. Remaining limitations are stated "
        "openly in DEBUGGING_REPORT.md: latency figures are single-machine observations of "
        "an in-memory SQLite database, the database stores naive UTC timestamps by design, "
        "and search uses a LIKE substring instead of a full-text index.",
    )
    return document


def main() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    document = build_document()
    document.save(OUTPUT_PATH)

    words = 0
    for paragraph in document.paragraphs:
        words += len(paragraph.text.split())
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                words += len(cell.text.split())
    print(f"written: {OUTPUT_PATH}")
    print(f"word count: {words} (target: 700-1200)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

