from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # optional for the offline tool layer
    load_dotenv = lambda: None


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str | None = None
    executor: str = "local"
    docker_image: str = "gcc:14"
    docker_workers: int = 2
    docker_memory: str = "256m"
    docker_cpus: str = "1.0"
    docker_network: bool = False
    memory_limit_mb: int | None = None
    run_timeout: float = 2.0
    compile_timeout: float = 10.0
    stress_timeout: float = 2.0

    @property
    def llm_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def is_sandboxed(self) -> bool:
        return self.executor == "docker"


def get_settings() -> Settings:
    load_dotenv()
    limit = _int("ACM_MEMORY_LIMIT_MB", 0)
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL"),
        openai_model=os.getenv("OPENAI_MODEL"),
        executor=(os.getenv("ACM_EXECUTOR") or "local").strip().lower(),
        docker_image=os.getenv("ACM_DOCKER_IMAGE") or "gcc:14",
        docker_workers=_int("ACM_DOCKER_WORKERS", 2),
        docker_memory=os.getenv("ACM_DOCKER_MEMORY") or "256m",
        docker_cpus=os.getenv("ACM_DOCKER_CPUS") or "1.0",
        docker_network=_bool("ACM_DOCKER_NETWORK", False),
        memory_limit_mb=limit or None,
        run_timeout=float(_int("ACM_RUN_TIMEOUT_MS", 2000)) / 1000.0,
        compile_timeout=float(_int("ACM_COMPILE_TIMEOUT_MS", 10_000)) / 1000.0,
        stress_timeout=float(_int("ACM_STRESS_TIMEOUT_MS", 2000)) / 1000.0,
    )
