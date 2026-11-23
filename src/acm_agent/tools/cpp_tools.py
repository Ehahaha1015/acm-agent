from __future__ import annotations

from pathlib import Path

from acm_agent.execution.backend import BackendUnavailable
from acm_agent.execution.executor import compile_program, run_program
from acm_agent.tools._support import backend, compile_timeout, sandbox_unavailable


def check_cpp(code: str, timeout: float | None = None) -> dict:
    """Compile on the selected backend and clean up all temporary artifacts."""
    try:
        engine = backend()
        with engine.workspace() as workspace:
            result = engine.compile(workspace, code, timeout=compile_timeout(timeout)).to_dict()
            result.pop("executable", None)
            result.pop("run_command", None)
            return result
    except BackendUnavailable as exc:
        return sandbox_unavailable(exc)


def compile_cpp(code: str, timeout: float = 10.0) -> dict:
    """Actually invoke g++ and return compiler status/diagnostics."""
    return compile_program(code, timeout=timeout).to_dict()


def run_cpp(executable: str, input_data: str = "", timeout: float = 2.0) -> dict:
    """Run an executable path returned by :func:`compile_cpp`. Trusted code only."""
    return run_program(Path(executable), input_data, timeout=timeout).to_dict()
