"""Pluggable execution backends.

Every C++ tool talks to an :class:`ExecutionBackend` instead of calling ``subprocess``
directly, so the same judge/stress semantics run either on the local machine or inside
pooled, network-disabled Docker containers.

* :class:`LocalBackend` — subprocess execution, **trusted code only**.
* :class:`DockerBackend` — long-lived ``gcc`` containers reused across compilations
  (worker pooling), with ``--network=none``, a read-only root filesystem, dropped
  capabilities, ``no-new-privileges``, pids/memory/CPU limits and an in-container
  ``timeout -s KILL`` guard.

Backends are process-wide singletons created by :func:`get_backend`, which reads
``ACM_EXECUTOR=local|docker`` from the environment. ``reset_backend`` exists for tests.
"""

from __future__ import annotations

import shlex
import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Protocol

from acm_agent.execution.executor import (
    OUTPUT_LIMIT_EXIT_CODE,
    CompileResult,
    ExecutionResult,
    compile_program,
    run_command,
    run_program,
    truncate_output,
)
from acm_agent.execution.languages import normalize_language, program_plan

DOCKER_TIMEOUT_EXIT_CODES = frozenset({124, 137, 143})
CONTAINER_WORKROOT = "/tmp/acm-agent"


class BackendUnavailable(RuntimeError):
    """Raised when the selected backend cannot run on this host."""


Runner = Callable[..., tuple[int | None, str, str, bool]]


class ExecutionBackend(Protocol):
    """Minimal surface the judge, compare and stress tools rely on."""

    name: str

    def workspace(self) -> Any:  # context manager yielding a workspace handle
        ...

    def workspaces(self, count: int) -> Any:
        ...

    def compile(self, workspace: str, code: str, *, timeout: float = 10.0, language: str = "cpp") -> CompileResult:
        ...

    def run(
        self,
        workspace: str,
        compiled: CompileResult,
        input_data: str = "",
        *,
        timeout: float = 2.0,
    ) -> ExecutionResult:
        ...

    def close(self) -> None:
        ...


# --------------------------------------------------------------------------------------
# Local subprocess backend
# --------------------------------------------------------------------------------------


@dataclass
class LocalBackend:
    """Subprocess backend. Runs whatever it is given: trusted submissions only."""

    name: str = "local"
    memory_limit_mb: int | None = None
    _roots: list[str] = field(default_factory=list, init=False, repr=False)

    @contextmanager
    def workspace(self) -> Iterator[str]:
        root = tempfile.mkdtemp(prefix="acm-agent-")
        self._roots.append(root)
        try:
            yield root
        finally:
            self._roots = [item for item in self._roots if item != root]
            shutil.rmtree(root, ignore_errors=True)

    def compile(self, workspace: str, code: str, *, timeout: float = 10.0, language: str = "cpp") -> CompileResult:
        return compile_program(code, timeout=timeout, workdir=workspace, language=language)

    @contextmanager
    def workspaces(self, count: int) -> Iterator[list[str]]:
        with ExitStack() as stack:
            yield [stack.enter_context(self.workspace()) for _ in range(count)]

    def run(
        self,
        workspace: str,
        compiled: CompileResult,
        input_data: str = "",
        *,
        timeout: float = 2.0,
    ) -> ExecutionResult:
        if not compiled.executable:
            return ExecutionResult("RUNTIME_ERROR", stderr="no executable was produced")
        return run_program(
            compiled.executable,
            input_data,
            timeout=timeout,
            memory_limit_mb=None if compiled.language == "java" else self.memory_limit_mb,
            command=compiled.run_command,
        )

    def close(self) -> None:
        for root in list(self._roots):
            shutil.rmtree(root, ignore_errors=True)
        self._roots.clear()


# --------------------------------------------------------------------------------------
# Docker backend with a persistent worker pool
# --------------------------------------------------------------------------------------


def _docker_runner(
    argv: Sequence[str], input_text: str = "", timeout: float = 120.0
) -> tuple[int | None, str, str, bool]:
    """Default transport: run the ``docker`` CLI and capture its output."""
    try:
        stdout, stderr, code, timed_out, _ = run_command(
            argv, input_text=input_text, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise BackendUnavailable("the docker CLI was not found on PATH") from exc
    return code, stdout, stderr, timed_out


@dataclass
class DockerBackend:
    """Reusable containers that compile and run untrusted submissions in isolation."""

    image: str = "acm-agent-runtime:latest"
    workers: int = 2
    memory: str = "512m"
    cpus: str = "1.0"
    network: bool = False
    compile_timeout: float = 30.0
    runner: Runner = _docker_runner
    name: str = "docker"
    _idle: list[str] = field(default_factory=list, init=False, repr=False)
    _known: set[str] = field(default_factory=set, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _slots: threading.BoundedSemaphore | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._slots = threading.BoundedSemaphore(max(1, self.workers))

    # -- docker plumbing ---------------------------------------------------------------

    def _cli(
        self, args: Sequence[str], *, input_text: str = "", timeout: float = 120.0
    ) -> tuple[int | None, str, str, bool]:
        return self.runner(["docker", *args], input_text, timeout)

    def run_options(self) -> list[str]:
        """Isolation flags shared by the pool containers (also useful in tests)."""
        options = [
            "--read-only",
            "--pids-limit=64",
            f"--memory={self.memory}",
            f"--cpus={self.cpus}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            # Compiled C/C++ programs live here; Docker's tmpfs defaults to noexec.
            "/tmp:rw,exec,nosuid,nodev,size=64m",
        ]
        options += ["--network=none"] if not self.network else []
        return options

    def available(self, *, timeout: float = 20.0) -> bool:
        try:
            code, _, _, _ = self._cli(
                ["version", "--format", "{{.Server.Version}}"], timeout=timeout
            )
        except BackendUnavailable:
            return False
        return code == 0

    def _start_container(self, timeout: float = 120.0) -> str:
        code, stdout, stderr, _ = self._cli(
            ["run", "-d", "--rm", *self.run_options(), self.image, "sleep", "infinity"],
            timeout=timeout,
        )
        container = stdout.strip().splitlines()[-1].strip() if stdout.strip() else ""
        if code != 0 or not container:
            raise BackendUnavailable(
                f"could not start docker worker ({self.image}): {stderr.strip() or code}"
            )
        return container

    def _is_running(self, container: str) -> bool:
        code, stdout, _, _ = self._cli(
            ["inspect", "-f", "{{.State.Running}}", container], timeout=30.0
        )
        return code == 0 and stdout.strip().lower() == "true"

    def _acquire(self, *, timeout: float = 120.0) -> str:
        """Lease one worker container, waiting when every slot is busy."""
        slots = self._slots
        assert slots is not None
        if not slots.acquire(timeout=timeout):
            raise BackendUnavailable("docker worker pool is exhausted")
        try:
            with self._lock:
                while self._idle:
                    container = self._idle.pop()
                    if self._is_running(container):
                        return container
            container = self._start_container()
            with self._lock:
                self._known.add(container)
            return container
        except Exception:
            slots.release()
            raise

    def _release(self, container: str) -> None:
        slots = self._slots
        assert slots is not None
        try:
            if self._is_running(container):
                with self._lock:
                    self._idle.append(container)
            else:
                with self._lock:
                    self._known.discard(container)
        finally:
            slots.release()

    def warmup(self) -> int:
        """Pre-start the pool so the first submission does not pay container startup."""
        containers: list[str] = []
        for _ in range(max(1, self.workers)):
            try:
                containers.append(self._acquire())
            except BackendUnavailable:
                break
        for container in containers:
            self._release(container)
        return len(containers)

    def live_containers(self) -> list[str]:
        with self._lock:
            return sorted(self._known)

    # -- backend protocol --------------------------------------------------------------

    @contextmanager
    def workspace(self) -> Iterator[str]:
        with self.workspaces(1) as workspaces:
            yield workspaces[0]

    @contextmanager
    def workspaces(self, count: int) -> Iterator[list[str]]:
        # One operation leases one worker, regardless of how many programs it uses.
        # Nested worker leases deadlock when compare/stress need more than pool size.
        container = self._acquire()
        directory = f"{CONTAINER_WORKROOT}/{uuid.uuid4().hex[:12]}"
        try:
            yield [f"docker://{container}{directory}/{i}" for i in range(count)]
        finally:
            try:
                self._cli(["exec", container, "sh", "-c", f"rm -rf {directory}"], timeout=60.0)
            finally:
                self._release(container)

    @staticmethod
    def _split(workspace: str) -> tuple[str, str]:
        if not workspace.startswith("docker://") or "/" not in workspace[9:]:
            raise ValueError(f"not a docker workspace handle: {workspace!r}")
        container, directory = workspace[len("docker://"):].split("/", 1)
        return container, "/" + directory

    def _exec(
        self,
        container: str,
        script: str,
        *,
        input_text: str = "",
        timeout: float = 120.0,
    ) -> tuple[int | None, str, str, bool]:
        return self._cli(
            ["exec", "-i", container, "sh", "-c", script],
            input_text=input_text,
            timeout=timeout,
        )

    def compile(self, workspace: str, code: str, *, timeout: float = 10.0, language: str = "cpp") -> CompileResult:
        try:
            language = normalize_language(language)
        except ValueError as exc:
            return CompileResult("UNSUPPORTED_LANGUAGE", stderr=str(exc))
        container, directory = self._split(workspace)
        budget = max(0.01, timeout)
        plan = program_plan(language, PurePosixPath(directory), docker=True)
        prepare = (
            f"mkdir -p {directory} && cat > {plan.source} && "
            f"timeout -s KILL {budget:.2f}s {shlex.join(plan.compile_command)} && test -f {plan.artifact}"
        )
        exit_code, stdout, stderr, timed_out = self._exec(
            container, prepare, input_text=code, timeout=budget + 60.0
        )
        executable = f"docker://{container}{plan.artifact}"
        if timed_out or exit_code in DOCKER_TIMEOUT_EXIT_CODES:
            return CompileResult(
                "COMPILE_TIMEOUT",
                stdout=stdout,
                stderr=stderr or "compilation exceeded the time limit",
                exit_code=exit_code,
                language=language,
            )
        ok = exit_code == 0
        if not ok and not stderr and language == "java":
            stderr = "Java submissions must declare class Main without a package."
        return CompileResult(
            status="COMPILE_OK" if ok else ("TOOLCHAIN_UNAVAILABLE" if exit_code == 127 else "COMPILE_ERROR"),
            executable=executable if ok else None,
            stdout=truncate_output(stdout),
            stderr=truncate_output(stderr),
            exit_code=exit_code,
            command=["docker", "exec", container, *plan.compile_command],
            language=language,
            run_command=plan.run_command if ok else None,
        )

    def run(
        self,
        workspace: str,
        compiled: CompileResult,
        input_data: str = "",
        *,
        timeout: float = 2.0,
    ) -> ExecutionResult:
        if not compiled.executable:
            return ExecutionResult("RUNTIME_ERROR", stderr="no executable was produced")
        container, program = self._split(compiled.executable)
        _, working_directory = self._split(workspace)
        budget = max(0.01, timeout)
        exit_code, stdout, stderr, client_timeout = self._exec(
            container,
            f"cd {working_directory} && timeout -s KILL {budget:.2f}s {shlex.join(compiled.run_command or [program])}",
            input_text=input_data,
            timeout=budget + 30.0,
        )
        if client_timeout or exit_code in DOCKER_TIMEOUT_EXIT_CODES:
            return ExecutionResult(
                "TIME_LIMIT_EXCEEDED",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=True,
            )
        status = "OK" if exit_code == 0 else "RUNTIME_ERROR"
        if exit_code == OUTPUT_LIMIT_EXIT_CODE:
            status = "OUTPUT_LIMIT_EXCEEDED"
        return ExecutionResult(status, stdout=stdout, stderr=stderr, exit_code=exit_code)

    def close(self) -> None:
        with self._lock:
            containers = sorted(self._known)
            self._known.clear()
            self._idle.clear()
        for container in containers:
            self._cli(["rm", "-f", container], timeout=60.0)


# --------------------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------------------

_BACKEND: ExecutionBackend | None = None
_BACKEND_LOCK = threading.Lock()


def build_backend() -> ExecutionBackend:
    from acm_agent.config import get_settings

    settings = get_settings()
    if settings.executor == "docker":
        return DockerBackend(
            image=settings.docker_image,
            workers=settings.docker_workers,
            memory=settings.docker_memory,
            cpus=settings.docker_cpus,
            network=settings.docker_network,
        )
    if settings.executor != "local":
        raise BackendUnavailable(f"Unknown ACM_EXECUTOR: {settings.executor}")
    return LocalBackend(memory_limit_mb=settings.memory_limit_mb)


def get_backend() -> ExecutionBackend:
    """Return the process-wide backend chosen by ``ACM_EXECUTOR``."""
    global _BACKEND
    if _BACKEND is None:
        with _BACKEND_LOCK:
            if _BACKEND is None:
                _BACKEND = build_backend()
    return _BACKEND


def set_backend(backend: ExecutionBackend | None) -> None:
    """Install a specific backend (used by tests and by ``acm-agent --executor``)."""
    global _BACKEND
    with _BACKEND_LOCK:
        _BACKEND = backend


def reset_backend() -> None:
    """Drop the cached backend, stopping pooled containers if there were any."""
    global _BACKEND
    with _BACKEND_LOCK:
        backend, _BACKEND = _BACKEND, None
    if backend is not None:
        backend.close()
