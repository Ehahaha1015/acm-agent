"""LLM-facing tool wrappers with JSON-safe signatures.

The Agents SDK derives a JSON schema from each Python signature through pydantic, and
pydantic cannot describe a **callable** parameter. The core tools accept an optional
``progress`` observer (used by the streaming layer), so they are wrapped here with plain
JSON-safe signatures. Docstrings matter too: they are what a hosted model reads when it
chooses a tool.
"""

from __future__ import annotations

from acm_agent.execution.executor import compile_program
from acm_agent.tools.cpp_tools import run_cpp
from acm_agent.tools.judge_tools import compare_cpp, judge_cpp
from acm_agent.tools.stress_tools import stress_cpp

__all__ = ["compare_cpp_tool", "compile_cpp_tool", "judge_cpp_tool", "run_cpp_tool", "stress_cpp_tool"]


def compile_cpp_tool(code: str) -> dict:
    """Compile C++20 source with g++ and return the real compiler verdict.

    Returns status COMPILE_OK, COMPILE_ERROR or COMPILE_TIMEOUT plus compiler
    diagnostics and the executable path to pass to run_cpp_tool.
    """
    return compile_program(code).to_dict()


def run_cpp_tool(executable: str, input_data: str = "", timeout: float = 2.0) -> dict:
    """Run an executable previously returned by compile_cpp_tool on the given stdin.

    Returns status OK, TIME_LIMIT_EXCEEDED or RUNTIME_ERROR with stdout/stderr.
    Only executable paths from this session are valid.
    """
    return run_cpp(executable, input_data, timeout=timeout)


def judge_cpp_tool(code: str, input_data: str, timeout: float = 2.0) -> dict:
    """Compile and run one C++ submission against one test input.

    Use this to check a single test: returns COMPILE_ERROR, OK, TIME_LIMIT_EXCEEDED or
    RUNTIME_ERROR with the actual observed stdout.
    """
    return judge_cpp(code, input_data, timeout=timeout)


def compare_cpp_tool(
    candidate_code: str, reference_code: str, test_cases: list[str], timeout: float = 2.0
) -> dict:
    """Differential-test candidate C++ against a reference C++ on explicit test cases.

    Compares whitespace-normalized stdout per case and returns the first mismatch with
    the offending input, or ALL_TESTS_PASSED. Passing finite tests is not a proof.
    """
    return compare_cpp(candidate_code, reference_code, test_cases, timeout=timeout)


def stress_cpp_tool(
    candidate_code: str,
    reference_code: str,
    generator_code: str,
    iterations: int = 1000,
    start_seed: int = 1,
    timeout: float = 2.0,
) -> dict:
    """Random stress test: the generator reads a seed from stdin and prints a test case.

    Every counterexample is reproducible because the failing seed and the complete
    generated input are returned. iterations must be between 1 and 10000.
    """
    return stress_cpp(
        candidate_code,
        reference_code,
        generator_code,
        iterations=iterations,
        start_seed=start_seed,
        timeout=timeout,
    )
