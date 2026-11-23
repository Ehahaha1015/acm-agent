from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import dotenv_values
except ImportError:  # optional for the offline tool layer
    def dotenv_values(path):
        return {}


def _int(env: Mapping, name: str, default: int) -> int:
    try:
        return int(env.get(name, "") or default)
    except ValueError:
        return default


def _bool(env: Mapping, name: str, default: bool = False) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    provider: str = "openai"
    database: str = "workspace/acm_agent.sqlite3"
    openai_api_key: str | None = field(default=None, repr=False)
    openai_base_url: str | None = None
    openai_model: str | None = None
    executor: str = "local"
    cpp_compiler: str = "g++"
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
        return bool(self.openai_api_key and self.openai_model and
                    self.openai_api_key != "your_api_key_here")

    @property
    def is_deepseek(self) -> bool:
        return self.provider == "deepseek" or urlparse(self.openai_base_url or "").hostname == "api.deepseek.com"

    @property
    def is_sandboxed(self) -> bool:
        return self.executor == "docker"


def get_settings() -> Settings:
    # Do not copy .env keys into os.environ: compiled subprocesses must not inherit them.
    # Read each time so local configuration edits are visible without cached credentials.
    env = {**dotenv_values(Path.cwd() / ".env"), **os.environ}
    provider = (env.get("ACM_MODEL_PROVIDER") or (
        "deepseek" if env.get("DEEPSEEK_API_KEY") and not env.get("OPENAI_API_KEY") else "openai"
    )).strip().lower()
    deepseek = provider == "deepseek"
    limit = _int(env, "ACM_MEMORY_LIMIT_MB", 0)
    return Settings(
        provider=provider,
        database=env.get("ACM_DATABASE") or "workspace/acm_agent.sqlite3",
        openai_api_key=env.get("DEEPSEEK_API_KEY") if deepseek else env.get("OPENAI_API_KEY"),
        openai_base_url="https://api.deepseek.com" if deepseek else env.get("OPENAI_BASE_URL"),
        openai_model=(env.get("DEEPSEEK_MODEL") or "deepseek-flash") if deepseek else env.get("OPENAI_MODEL"),
        executor=(env.get("ACM_EXECUTOR") or "local").strip().lower(),
        cpp_compiler=env.get("ACM_CXX") or "g++",
        docker_image=env.get("ACM_DOCKER_IMAGE") or "gcc:14",
        docker_workers=max(1, _int(env, "ACM_DOCKER_WORKERS", 2)),
        docker_memory=env.get("ACM_DOCKER_MEMORY") or "256m",
        docker_cpus=env.get("ACM_DOCKER_CPUS") or "1.0",
        docker_network=_bool(env, "ACM_DOCKER_NETWORK", False),
        memory_limit_mb=limit if limit > 0 else None,
        run_timeout=max(1, _int(env, "ACM_RUN_TIMEOUT_MS", 2000)) / 1000.0,
        compile_timeout=max(1, _int(env, "ACM_COMPILE_TIMEOUT_MS", 10_000)) / 1000.0,
        stress_timeout=max(1, _int(env, "ACM_STRESS_TIMEOUT_MS", 2000)) / 1000.0,
    )
