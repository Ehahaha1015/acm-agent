from __future__ import annotations

from acm_agent.execution.backend import BackendUnavailable
from acm_agent.tools._support import (
    Progress,
    backend,
    compile_timeout,
    notify,
    run_timeout,
    sandbox_unavailable,
)


def judge_cpp(
    code: str,
    input_data: str,
    timeout: float | None = None,
    progress: Progress | None = None,
) -> dict:
    """Compile and run one submission against one input on the active backend."""
    try:
        engine = backend()
        with engine.workspace() as workspace:
            notify(progress, stage="compile", backend=engine.name)
            compiled = engine.compile(workspace, code, timeout=compile_timeout(None))
            if compiled.status != "COMPILE_OK":
                notify(progress, stage="compile_failed", status=compiled.status)
                return {
                    "status": "COMPILE_TIMEOUT" if compiled.status == "COMPILE_TIMEOUT" else "COMPILE_ERROR",
                    "compile": compiled.to_dict(),
                    "stdout": "",
                    "stderr": compiled.stderr,
                }
            notify(progress, stage="run", timeout=run_timeout(timeout))
            result = engine.run(workspace, compiled, input_data, timeout=run_timeout(timeout))
            notify(progress, stage="ran", status=result.status)
            return {"status": result.status, **result.to_dict()}
    except BackendUnavailable as exc:
        return sandbox_unavailable(exc)


def normalize_output(output: str) -> str:
    return " ".join(output.split())


def compare_cpp(
    candidate_code: str,
    reference_code: str,
    test_cases: list[str],
    timeout: float | None = None,
    progress: Progress | None = None,
) -> dict:
    """Differential-test candidate against reference on explicit cases."""
    try:
        engine = backend()
        with engine.workspace() as candidate_ws, engine.workspace() as reference_ws:
            notify(progress, stage="compile", target="candidate")
            candidate = engine.compile(candidate_ws, candidate_code, timeout=compile_timeout(None))
            if candidate.status != "COMPILE_OK":
                return {
                    "status": f"CANDIDATE_{candidate.status}",
                    "compile": candidate.to_dict(),
                }
            notify(progress, stage="compile", target="reference")
            reference = engine.compile(reference_ws, reference_code, timeout=compile_timeout(None))
            if reference.status != "COMPILE_OK":
                return {
                    "status": f"REFERENCE_{reference.status}",
                    "compile": reference.to_dict(),
                }
            budget = run_timeout(timeout)
            for number, case in enumerate(test_cases, 1):
                notify(progress, stage="case", test_number=number, total=len(test_cases))
                cand = engine.run(candidate_ws, candidate, case, timeout=budget)
                if cand.status != "OK":
                    return {
                        "status": "CANDIDATE_TLE" if cand.timed_out else "CANDIDATE_RUNTIME_ERROR",
                        "test_number": number,
                        "input": case,
                        "candidate": cand.to_dict(),
                    }
                ref = engine.run(reference_ws, reference, case, timeout=budget)
                if ref.status != "OK":
                    return {
                        "status": "REFERENCE_TLE" if ref.timed_out else "REFERENCE_RUNTIME_ERROR",
                        "test_number": number,
                        "input": case,
                        "reference": ref.to_dict(),
                    }
                if normalize_output(cand.stdout) != normalize_output(ref.stdout):
                    notify(progress, stage="mismatch", test_number=number)
                    return {
                        "status": "WRONG_ANSWER_FOUND",
                        "test_number": number,
                        "input": case,
                        "candidate_output": cand.stdout,
                        "reference_output": ref.stdout,
                    }
            return {
                "status": "ALL_TESTS_PASSED",
                "tests_run": len(test_cases),
                "warning": "Finite tests do not prove correctness.",
            }
    except BackendUnavailable as exc:
        return sandbox_unavailable(exc)
