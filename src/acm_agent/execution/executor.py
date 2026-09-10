"""Process execution primitives shared by every C++ tool.

The local executor is intentionally explicit: it is suitable for trusted code only.
Production deployments should use :class:`acm_agent.execution.sandbox.DockerExecutor`
(see ``backend.py`` for the pluggable selector).

Two properties matter for a judge and are enforced here:

* **Byte-exact decoding.** Compiler diagnostics and judged output are decoded as UTF-8
  with ``errors="replace"`` instead of the legacy locale codec, so a Chinese error
  message or a UTF-8 byte sequence can never raise ``UnicodeDecodeError`` mid-judge.
* **Whole-process-tree termination.** A timed-out submission is killed together with
  its children (``taskkill /T`` on Windows, ``killpg`` on POSIX), so a program that
  forks or spawns threads cannot outlive its time limit.
"""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_OUTPUT = 16_384
DEFAULT_COMPILER = os.getenv("ACM_CXX", "g++")
DEFAULT_FLAGS: tuple[str, ...] = ("-std=c++20", "-O2", "-pipe", "-Wall", "-Wextra")
KILL_GRACE_SECONDS = 5.0

# Every capture goes through these so output decoding never depends on the host locale.
TEXT_KWARGS: dict[str, Any] = {"text": True, "encoding": "utf-8", "errors": "replace"}


def truncate_output(value: str | bytes | None, limit: int = MAX_OUTPUT) -> str:
    text = (value or b"").decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated after {limit} characters]"


@dataclass(slots=True)
class CompileResult:
    status: str
    executable: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    command: list[str] | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ExecutionResult:
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _popen(
    command: Sequence[str],
    *,
    cwd: str | Path | None,
    stdin_pipe: bool,
    preexec_fn: Any = None,
) -> subprocess.Popen:
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "cwd": str(cwd) if cwd is not None else None,
        **TEXT_KWARGS,
    }
    if preexec_fn is not None:
        kwargs["preexec_fn"] = preexec_fn
    if stdin_pipe:
        kwargs["stdin"] = subprocess.PIPE
    if os.name == "nt":
        # Never flash a console window for a judged process, and keep it in our session.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        # Own process group so a timeout can reap grandchildren too.
        kwargs["start_new_session"] = True
    return subprocess.Popen(list(command), **kwargs)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
            **TEXT_KWARGS,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
    try:
        proc.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        proc.kill()


def _memory_limiter(memory_limit_mb: int | None):
    """POSIX-only address-space limit applied in the child before ``exec``."""
    if not memory_limit_mb or os.name == "nt":
        return None

    def _apply() -> None:  # pragma: no cover - exercised on Linux CI only
        import resource

        limit = int(memory_limit_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return _apply


def _communicate(
    proc: subprocess.Popen, input_text: str, timeout: float
) -> tuple[str, str, int | None, bool]:
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
        return stdout or "", stderr or "", proc.returncode, False
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        return stdout or "", stderr or "", None, True


def run_command(
    command: Sequence[str],
    *,
    input_text: str = "",
    timeout: float = 2.0,
    cwd: str | Path | None = None,
    memory_limit_mb: int | None = None,
) -> tuple[str, str, int | None, bool, int]:
    """Run one command, returning decoded output, exit code, timeout flag and duration."""
    started = time.monotonic()
    proc = _popen(
        command,
        cwd=cwd,
        stdin_pipe=True,
        preexec_fn=_memory_limiter(memory_limit_mb),
    )
    stdout, stderr, exit_code, timed_out = _communicate(proc, input_text, timeout)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return stdout, stderr, exit_code, timed_out, elapsed_ms


def compile_program(
    code: str,
    *,
    timeout: float = 10.0,
    workdir: str | Path | None = None,
    flags: Sequence[str] | None = None,
    compiler: str | None = None,
) -> CompileResult:
    """Compile C++20 source with g++, returning diagnostics and an executable path."""
    if not isinstance(code, str):
        return CompileResult("COMPILE_ERROR", stderr="code must be a string")
    root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="acm-agent-"))
    root.mkdir(parents=True, exist_ok=True)
    source = root / "source.cpp"
    executable = root / ("program.exe" if os.name == "nt" else "program")
    source.write_text(code, encoding="utf-8")
    command = [
        compiler or DEFAULT_COMPILER,
        str(source),
        *(flags if flags is not None else DEFAULT_FLAGS),
        "-o",
        str(executable),
    ]
    try:
        stdout, stderr, exit_code, timed_out, elapsed_ms = run_command(
            command, timeout=timeout, cwd=root
        )
    except FileNotFoundError:
        return CompileResult(
            "COMPILE_ERROR",
            stderr=f"{command[0]} was not found on PATH",
            command=command,
        )
    if timed_out:
        return CompileResult(
            "COMPILE_TIMEOUT",
            stdout=stdout,
            stderr=stderr,
            command=command,
            duration_ms=elapsed_ms,
        )
    ok = exit_code == 0 and executable.exists()
    return CompileResult(
        status="COMPILE_OK" if ok else "COMPILE_ERROR",
        executable=str(executable) if ok else None,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        command=command,
        duration_ms=elapsed_ms,
    )


def run_program(
    executable: str | Path,
    input_data: str = "",
    *,
    timeout: float = 2.0,
    memory_limit_mb: int | None = None,
) -> ExecutionResult:
    """Run a compiled executable and classify OK/TLE/RE."""
    path = Path(executable)
    if not path.exists():
        return ExecutionResult("RUNTIME_ERROR", stderr=f"executable was not found: {path}")
    try:
        stdout, stderr, exit_code, timed_out, elapsed_ms = run_command(
            [str(path)],
            input_text=input_data,
            timeout=timeout,
            cwd=path.parent,
            memory_limit_mb=memory_limit_mb,
        )
    except FileNotFoundError:
        return ExecutionResult("RUNTIME_ERROR", stderr="executable was not found")
    if timed_out:
        return ExecutionResult(
            "TIME_LIMIT_EXCEEDED",
            stdout=stdout,
            stderr=stderr,
            exit_code=None,
            timed_out=True,
            duration_ms=elapsed_ms,
        )
    status = "OK" if exit_code == 0 else "RUNTIME_ERROR"
    return ExecutionResult(
        status,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=elapsed_ms,
    )
