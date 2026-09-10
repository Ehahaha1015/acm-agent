from __future__ import annotations

from pathlib import Path

from acm_agent.execution.executor import compile_program, run_program


def compile_cpp(code: str, timeout: float = 10.0) -> dict:
    """Actually invoke g++ and return compiler status/diagnostics."""
    return compile_program(code, timeout=timeout).to_dict()


def run_cpp(executable: str, input_data: str = "", timeout: float = 2.0) -> dict:
    """Run an executable path returned by :func:`compile_cpp`. Trusted code only."""
    return run_program(Path(executable), input_data, timeout=timeout).to_dict()
