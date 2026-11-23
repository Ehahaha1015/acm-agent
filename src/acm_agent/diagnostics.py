"""Configuration diagnostics shared by the CLI and browser; never include credentials."""

import shutil

from acm_agent import __version__
from acm_agent.config import get_settings
from acm_agent.execution.languages import LANGUAGE_LABELS


def runtime_status() -> dict:
    settings = get_settings()
    commands = {
        "cpp": [settings.cpp_compiler], "c": [settings.c_compiler],
        "python": [settings.python_executable],
        "java": [settings.javac_executable, settings.java_executable],
    }
    return {
        "version": __version__,
        "supported_languages": list(LANGUAGE_LABELS),
        "runtimes": {
            language: {"label": LANGUAGE_LABELS[language],
                       "available": all(shutil.which(command) is not None for command in required)}
            for language, required in commands.items()
        },
        "runtime_scope": "local_host",
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
