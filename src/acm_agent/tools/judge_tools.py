import subprocess
import tempfile
from pathlib import Path

from agents import function_tool


MAX_OUTPUT_CHARS = 6000


def truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text

    return text[:MAX_OUTPUT_CHARS] + "\n...[output truncated]"


@function_tool
def judge_cpp(
    code: str,
    input_data: str = "",
) -> str:
    """
    Compile and execute a C++ program in one isolated temporary directory.

    Args:
        code:
            Complete C++ source code.

        input_data:
            Standard input passed to the program.

    Returns:
        Compilation or execution result including stdout,
        stderr and exit code.
    """

    print("\n[tool] judge_cpp called")

    with tempfile.TemporaryDirectory(
        prefix="acm_agent_"
    ) as temp_dir:

        temp_path = Path(temp_dir)

        source_file = temp_path / "main.cpp"
        binary_file = temp_path / "main"

        source_file.write_text(
            code,
            encoding="utf-8",
        )

        compile_command = [
            "g++",
            str(source_file),
            "-std=c++20",
            "-O2",
            "-pipe",
            "-Wall",
            "-Wextra",
            "-o",
            str(binary_file),
        ]

        try:
            compile_result = subprocess.run(
                compile_command,
                capture_output=True,
                text=True,
                timeout=10,
            )

        except subprocess.TimeoutExpired:
            return (
                "STATUS: COMPILE_TIMEOUT\n"
                "Compilation exceeded 10 seconds."
            )

        if compile_result.returncode != 0:
            return (
                "STATUS: COMPILE_ERROR\n\n"
                f"Exit code: {compile_result.returncode}\n\n"
                "stderr:\n"
                f"{truncate(compile_result.stderr)}"
            )

        try:
            run_result = subprocess.run(
                [str(binary_file)],
                input=input_data,
                capture_output=True,
                text=True,
                timeout=3,
            )

        except subprocess.TimeoutExpired:
            return (
                "STATUS: TIME_LIMIT_EXCEEDED\n"
                "Execution exceeded 3 seconds."
            )

        stdout = truncate(run_result.stdout)
        stderr = truncate(run_result.stderr)

        if run_result.returncode != 0:
            status = "RUNTIME_ERROR"
        else:
            status = "OK"

        return (
            f"STATUS: {status}\n"
            f"Exit code: {run_result.returncode}\n\n"
            f"stdout:\n{stdout or '(empty)'}\n\n"
            f"stderr:\n{stderr or '(empty)'}"
        )
