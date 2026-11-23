"""Compile or syntax-check any supported language using the selected backend."""

from acm_agent.execution.backend import BackendUnavailable
from acm_agent.execution.languages import normalize_language
from acm_agent.tools._support import backend, compile_timeout, sandbox_unavailable


def check_code(code: str, language: str = "cpp", timeout: float | None = None) -> dict:
    """Check one source file, then clean up its workspace without running user code."""
    try:
        language = normalize_language(language)
    except ValueError as exc:
        return {"status": "UNSUPPORTED_LANGUAGE", "message": str(exc)}
    try:
        engine = backend()
        with engine.workspace() as workspace:
            result = engine.compile(workspace, code, timeout=compile_timeout(timeout), language=language).to_dict()
            result.pop("executable", None)
            result.pop("run_command", None)
            return result
    except BackendUnavailable as exc:
        return sandbox_unavailable(exc)
