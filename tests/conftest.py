"""Shared pytest fixtures.

Force `ENVIRONMENT=test` before any `src.*` import so that code paths with
side effects on shared systems (GitHub repo creation, publishing) are
suppressed regardless of what a test body passes. Belt-and-suspenders with
the opt-in default on `ProjectCreate.create_repo`.
"""
from __future__ import annotations

import os

os.environ.setdefault("ENVIRONMENT", "test")
