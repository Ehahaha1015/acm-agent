"""LLM-facing tool wrappers with JSON-safe signatures.

The Agents SDK derives a JSON schema from each Python signature through pydantic, and
pydantic cannot describe a **callable** parameter. The core tools accept an optional
``progress`` observer (used by the streaming layer), so they are wrapped here with plain
JSON-safe signatures. Docstrings matter too: they are what a hosted model reads when it
chooses a tool.
"""

from __future__ import annotations

import asyncio

from acm_agent.execution.languages import Language
from acm_agent.tools import check_code, compare_code, run_code, stress_code
from acm_agent.tools.cpp_tools import check_cpp
from acm_agent.tools.judge_tools import compare_cpp, judge_cpp
from acm_agent.tools.stress_tools import stress_cpp

__all__ = [
    "compare_code_tool",
    "compare_cpp_tool",
    "compile_code_tool",
    "compile_cpp_tool",
    "judge_cpp_tool",
    "run_code_tool",
    "run_cpp_tool",
    "stress_code_tool",
    "stress_cpp_tool",
]


async def compile_code_tool(code: str, language: Language = "cpp") -> dict:
    """Compile C++20/C17/Java17 or syntax-check Python3 without executing user code.

    Java must use class Main without a package. Returns observed diagnostics and verdict.
    """
    return await asyncio.to_thread(check_code, code, language=language)


async def run_code_tool(code: str, input_data: str = "", language: Language = "cpp", timeout: float = 2.0) -> dict:
    """Compile/check then run cpp, c, python or java with stdin (which may be empty).

    Java uses class Main without a package. Returns real stdout/stderr and verdict.
    """
    return await asyncio.to_thread(run_code, code, input_data, language=language, timeout=timeout)


async def compare_code_tool(
    candidate_code: str, reference_code: str, test_cases: list[str],
    language: Language = "cpp", reference_language: Language | None = None, timeout: float = 2.0,
) -> dict:
    """Compare programs on explicit inputs, optionally using different languages.

    reference_language defaults to the candidate language. Reports the first mismatch.
    """
    return await asyncio.to_thread(compare_code, candidate_code, reference_code, test_cases,
                                   language=language, reference_language=reference_language,
                                   timeout=timeout, budget_seconds=30.0)


async def stress_code_tool(
    candidate_code: str, reference_code: str, generator_code: str,
    language: Language = "cpp", reference_language: Language | None = None,
    generator_language: Language | None = None, iterations: int = 100,
    start_seed: int = 1, timeout: float = 2.0,
) -> dict:
    """Stress-test programs in cpp/c/python/java, including mixed-language tests.

    The generator reads a numeric seed from stdin and outputs a test input.
    Reference/generator languages default to the candidate language. Returns reproducible
    counterexamples. Finite and random testing cannot prove correctness.
    """
    return await asyncio.to_thread(stress_code, candidate_code, reference_code, generator_code,
                                   language=language, reference_language=reference_language,
                                   generator_language=generator_language, iterations=iterations,
                                   start_seed=start_seed, timeout=timeout, budget_seconds=30.0)


async def compile_cpp_tool(code: str) -> dict:
    """Compile C++20 source with g++ and return the real compiler verdict.

    Returns status COMPILE_OK, COMPILE_ERROR or COMPILE_TIMEOUT plus compiler
    diagnostics. Temporary artifacts are cleaned up after compilation.
    """
    return await asyncio.to_thread(check_cpp, code)


async def run_cpp_tool(code: str, input_data: str = "", timeout: float = 2.0) -> dict:
    """Compile C++20 source and run it on the selected execution backend.

    Returns status OK, TIME_LIMIT_EXCEEDED or RUNTIME_ERROR with stdout/stderr.
    """
    return await asyncio.to_thread(judge_cpp, code, input_data, timeout=timeout)


async def judge_cpp_tool(code: str, input_data: str, timeout: float = 2.0) -> dict:
    """Compile and run one C++ submission against one test input.

    Use this to check a single test: returns COMPILE_ERROR, OK, TIME_LIMIT_EXCEEDED or
    RUNTIME_ERROR with the actual observed stdout.
    """
    return await asyncio.to_thread(judge_cpp, code, input_data, timeout=timeout)


async def compare_cpp_tool(
    candidate_code: str, reference_code: str, test_cases: list[str], timeout: float = 2.0
) -> dict:
    """Differential-test candidate C++ against a reference C++ on explicit test cases.

    Compares whitespace-normalized stdout per case and returns the first mismatch with
    the offending input, or ALL_TESTS_PASSED. Passing finite tests is not a proof.
    """
    return await asyncio.to_thread(
        compare_cpp, candidate_code, reference_code, test_cases, timeout=timeout,
        budget_seconds=30.0,
    )


async def stress_cpp_tool(
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
    return await asyncio.to_thread(
        stress_cpp,
        candidate_code,
        reference_code,
        generator_code,
        iterations=iterations,
        start_seed=start_seed,
        timeout=timeout,
        budget_seconds=30.0,
    )
