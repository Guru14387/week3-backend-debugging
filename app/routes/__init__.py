"""HTTP routes of the Week3 Backend Debugging API."""

from __future__ import annotations

from fastapi import APIRouter

from app.routes import tasks

__all__ = ["tasks"]
