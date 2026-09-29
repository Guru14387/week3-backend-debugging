"""Application factory and ASGI entry point.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routes import tasks

DESCRIPTION = """
A small but realistic task-management backend used for the Week 3 internship
assignment *Debugging, Testing and Error Resolution*. It exposes CRUD endpoints
for tasks, nested comment endpoints, filtering/search and an aggregated
statistics endpoint on top of a self-contained SQLite database.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the SQLite schema before the first request is served."""
    init_db()
    yield


app = FastAPI(
    title="Week3 Backend Debugging API",
    description=DESCRIPTION.strip(),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(tasks.router)


@app.get("/health", tags=["system"], summary="Liveness probe")
def health() -> dict[str, str]:
    """Return a small payload used by the startup smoke check."""
    return {"status": "ok", "service": app.title, "version": app.version}


if __name__ == "__main__":  # pragma: no cover - manual entry point
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
