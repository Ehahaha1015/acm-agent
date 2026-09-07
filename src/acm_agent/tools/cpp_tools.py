from pathlib import Path
import subprocess

from agents import function_tool


PROJECT_ROOT = Path(__file__).resolve().parents[3]

WORKSPACE = PROJECT_ROOT / "workspace"
SOURCE_FILE = WORKSPACE / "main.cpp"
BINARY_FILE = WORKSPACE / "main"


@function_tool
def compile_cpp(code: str) -> str:
    """
    Compile C++ source code using g++.

    Args:
        code: Complete C++ source code.

    Returns:
        Compilation result including compiler errors and warnings.
    """
    print("\n[tool] compile_cpp called")
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    SOURCE_FILE.write_text(
        code,
        encoding="utf-8",
    )

    command = [
        "g++",
        str(SOURCE_FILE),
        "-std=c++20",
        "-O2",
        "-pipe",
        "-Wall",
        "-Wextra",
        "-o",
        str(BINARY_FILE),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return "Compilation timed out after 10 seconds."

    if result.returncode != 0:
        return (
            "Compilation failed.\n\n"
            f"Exit code: {result.returncode}\n\n"
            f"stderr:\n{result.stderr}"
        )

    output = "Compilation succeeded."

    if result.stderr:
        output += f"\n\nCompiler warnings:\n{result.stderr}"

    return output


@function_tool
def run_cpp(input_data: str = "") -> str:
    """
    Run the most recently compiled C++ program.

    Args:
        input_data: Standard input passed to the program.

    Returns:
        Program stdout, stderr and exit code.
    """

    if not BINARY_FILE.exists():
        return "No compiled program exists. Call compile_cpp first."

    try:
        result = subprocess.run(
            [str(BINARY_FILE)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return "Program execution timed out after 3 seconds. Possible TLE or infinite loop."

    stdout = result.stdout
    stderr = result.stderr

    # 防止 Agent 被特别大的输出淹没
    max_chars = 6000

    if len(stdout) > max_chars:
        stdout = stdout[:max_chars] + "\n...[stdout truncated]"

    if len(stderr) > max_chars:
        stderr = stderr[:max_chars] + "\n...[stderr truncated]"

    return (
        f"Exit code: {result.returncode}\n\n"
        f"stdout:\n{stdout or '(empty)'}\n\n"
        f"stderr:\n{stderr or '(empty)'}"
    )
