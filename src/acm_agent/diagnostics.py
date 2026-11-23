"""Configuration diagnostics shared by the CLI and browser; never include credentials."""

import shutil

from acm_agent.config import get_settings


def runtime_status() -> dict:
    settings = get_settings()
    return {
        "version": "0.2.0",
        "executor": settings.executor,
        "compiler_available": shutil.which(settings.cpp_compiler) is not None,
        "docker_cli_available": shutil.which("docker") is not None,
        "model_configured": settings.llm_configured,
        "provider": "deepseek" if settings.is_deepseek else settings.provider,
        "model_name": settings.openai_model,
        "model": settings.openai_model if settings.llm_configured else None,
        "stress_budget_seconds": 30,
        "trusted_code_only": not settings.is_sandboxed,
    }
