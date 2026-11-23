"""Shared helpers for the C++ tools: backend access, timeouts and progress reporting."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any

from acm_agent.config import get_settings
from acm_agent.execution.backend import BackendUnavailable, ExecutionBackend, get_backend

Progress = Callable[[dict[str, Any]], None]


def backend() -> ExecutionBackend:
    return get_backend()


def run_timeout(timeout: float | None) -> float:
    return float(timeout) if timeout is not None else get_settings().run_timeout


def compile_timeout(timeout: float | None) -> float:
    return float(timeout) if timeout is not None else get_settings().compile_timeout


def notify(progress: Progress | None, **payload: Any) -> None:
    """Report a trace event. A broken observer must never break a real execution."""
    if progress is None:
        return
    with suppress(BackendUnavailable, RuntimeError, ValueError, TypeError, KeyError):
        progress(payload)


def sandbox_unavailable(exc: BackendUnavailable) -> dict:
    return {
        "status": "SANDBOX_UNAVAILABLE",
        "message": str(exc),
        "warning": (
            "ACM_EXECUTOR=docker is selected but no usable Docker worker was available. "
            "No code was executed; do not report any compile, run or WA/TLE result."
        ),
    }
