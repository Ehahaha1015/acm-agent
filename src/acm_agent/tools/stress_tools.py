from __future__ import annotations

import time

from acm_agent.execution.backend import BackendUnavailable
from acm_agent.execution.languages import normalize_language
from acm_agent.tools._support import (
    Progress,
    backend,
    compile_timeout,
    notify,
    run_timeout,
    sandbox_unavailable,
)
from acm_agent.tools.judge_tools import normalize_output

MAX_ITERATIONS = 10_000
PROGRESS_STEPS = 20


def stress_code(
    candidate_code: str,
    reference_code: str,
    generator_code: str,
    iterations: int = 1000,
    start_seed: int = 1,
    timeout: float | None = None,
    progress: Progress | None = None,
    budget_seconds: float | None = None,
    language: str = "cpp",
    reference_language: str | None = None,
    generator_language: str | None = None,
) -> dict:
    """Random stress test: the generator is fed seeds, so every counterexample repeats.

    ``budget_seconds`` bounds wall-clock time (used by the HTTP layer so a request can
    never hang on a long stress run); the partial result is reported honestly instead of
    being presented as a passed test.
    """
    if iterations < 1 or iterations > MAX_ITERATIONS:
        return {
            "status": "INVALID_ITERATIONS",
            "message": f"iterations must be between 1 and {MAX_ITERATIONS}",
        }
    try:
        language = normalize_language(language)
        reference_language = normalize_language(reference_language or language)
        generator_language = normalize_language(generator_language or language)
    except ValueError as exc:
        return {"status": "UNSUPPORTED_LANGUAGE", "message": str(exc)}
    languages = {"candidate": language, "reference": reference_language, "generator": generator_language}
    deadline = time.monotonic() + budget_seconds if budget_seconds else None
    cadence = max(1, iterations // PROGRESS_STEPS)
    try:
        engine = backend()
        programs = {
            "candidate": candidate_code,
            "reference": reference_code,
            "generator": generator_code,
        }
        with engine.workspaces(3) as leased:
            candidate_ws, reference_ws, generator_ws = leased
            workspaces = {
                "candidate": candidate_ws,
                "reference": reference_ws,
                "generator": generator_ws,
            }
            compiled = {}
            for name, code in programs.items():
                notify(progress, stage="compile", target=name)
                result = engine.compile(workspaces[name], code, timeout=compile_timeout(None), language=languages[name])
                if result.status != "COMPILE_OK":
                    return {"status": f"{name.upper()}_{result.status}", "compile": result.to_dict()}
                compiled[name] = result
            budget = run_timeout(timeout)
            for completed, seed in enumerate(range(start_seed, start_seed + iterations), 1):
                if deadline is not None and time.monotonic() > deadline:
                    notify(progress, stage="budget_exhausted", completed=completed - 1)
                    return {
                        "status": "STRESS_TIME_LIMIT",
                        "iterations_completed": completed - 1,
                        "iterations_requested": iterations,
                        "start_seed": start_seed,
                        "warning": (
                            "The stress budget expired before a counterexample was found. "
                            "This is not evidence that the candidate is correct."
                        ),
                    }
                generated = engine.run(generator_ws, compiled["generator"], f"{seed}\n", timeout=budget)
                if generated.status != "OK":
                    return {
                        "status": "GENERATOR_TLE" if generated.timed_out else f"GENERATOR_{generated.status}",
                        "seed": seed,
                        "generator": generated.to_dict(),
                    }
                if not generated.stdout.strip():
                    return {
                        "status": "GENERATOR_INVALID_OUTPUT",
                        "seed": seed,
                        "message": "generator produced empty output",
                    }
                case = generated.stdout
                candidate = engine.run(candidate_ws, compiled["candidate"], case, timeout=budget)
                if candidate.status != "OK":
                    return {
                        "status": "CANDIDATE_TLE" if candidate.timed_out else f"CANDIDATE_{candidate.status}",
                        "seed": seed,
                        "input": case,
                        "candidate": candidate.to_dict(),
                    }
                reference = engine.run(reference_ws, compiled["reference"], case, timeout=budget)
                if reference.status != "OK":
                    return {
                        "status": "REFERENCE_TLE" if reference.timed_out else f"REFERENCE_{reference.status}",
                        "seed": seed,
                        "input": case,
                        "reference": reference.to_dict(),
                    }
                if normalize_output(candidate.stdout) != normalize_output(reference.stdout):
                    notify(progress, stage="mismatch", seed=seed, completed=completed)
                    return {
                        "status": "WRONG_ANSWER_FOUND",
                        "seed": seed,
                        "input": case,
                        "candidate_output": candidate.stdout,
                        "reference_output": reference.stdout,
                        "iterations_completed": completed,
                        "languages": languages,
                    }
                if completed % cadence == 0 or completed == iterations:
                    notify(progress, stage="progress", completed=completed, total=iterations)
            return {
                "status": "ALL_STRESS_TESTS_PASSED",
                "iterations": iterations,
                "start_seed": start_seed,
                "languages": languages,
                "warning": "Random stress testing cannot prove correctness.",
            }
    except BackendUnavailable as exc:
        return sandbox_unavailable(exc)


def stress_cpp(
    candidate_code: str, reference_code: str, generator_code: str,
    iterations: int = 1000, start_seed: int = 1, timeout: float | None = None,
    progress: Progress | None = None, budget_seconds: float | None = None,
) -> dict:
    """Compatibility wrapper for C++20 stress tests."""
    return stress_code(candidate_code, reference_code, generator_code,
                       iterations=iterations, start_seed=start_seed, timeout=timeout,
                       progress=progress, budget_seconds=budget_seconds)
