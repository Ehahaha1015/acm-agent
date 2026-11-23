"""Language-specific commands shared by local execution and Docker workers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from acm_agent.config import get_settings

Language = Literal["cpp", "c", "python", "java"]
LANGUAGE_LABELS = {"cpp": "C++20", "c": "C17", "python": "Python 3", "java": "Java 17"}
ALIASES = {"c++": "cpp", "cc": "cpp", "cxx": "cpp", "py": "python", "python3": "python"}
NATIVE_FLAGS = ["-O2", "-pipe", "-Wall", "-Wextra"]
JVM_FLAGS = [
    "-Xms16m", "-Xmx128m", "-XX:+UseSerialGC", "-XX:ReservedCodeCacheSize=32m",
    "-XX:MaxMetaspaceSize=96m", "-XX:CompressedClassSpaceSize=32m",
]
ENCODING_FLAGS = [
    "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8",
    "-Dstdin.encoding=UTF-8", "-Dsun.stdout.encoding=UTF-8", "-Dsun.stderr.encoding=UTF-8",
]


def normalize_language(language: str) -> str:
    value = ALIASES.get(language.strip().lower(), language.strip().lower())
    if value not in LANGUAGE_LABELS:
        raise ValueError(f"Unsupported language: {language}. Choose cpp, c, python or java.")
    return value


@dataclass(frozen=True)
class ProgramPlan:
    source: str
    artifact: str
    compile_command: list[str]
    run_command: list[str]


def program_plan(language: str, root: Path | PurePosixPath, *, docker: bool = False) -> ProgramPlan:
    language = normalize_language(language)
    settings = get_settings()
    executable = str(root / ("program.exe" if os.name == "nt" and not docker else "program"))
    if language in {"cpp", "c"}:
        source = str(root / ("source.cpp" if language == "cpp" else "source.c"))
        compiler = ("g++" if language == "cpp" else "gcc") if docker else (
            settings.cpp_compiler if language == "cpp" else settings.c_compiler
        )
        flags = ["-std=c++20" if language == "cpp" else "-std=c17", *NATIVE_FLAGS]
        command = [compiler, source, *flags, "-o", executable]
        if language == "c":
            command.append("-lm")
        return ProgramPlan(source, executable, command, [executable])
    if language == "python":
        python = "python3" if docker else settings.python_executable
        source = str(root / "main.py")
        return ProgramPlan(
            source, source,
            [python, "-I", "-X", "utf8", "-m", "py_compile", source],
            [python, "-I", "-X", "utf8", source],
        )
    source = str(root / "Main.java")
    javac = "javac" if docker else settings.javac_executable
    java = "java" if docker else settings.java_executable
    return ProgramPlan(
        source, str(root / "Main.class"),
        [javac, "-J-Xmx128m", "-J-XX:+UseSerialGC", *(f"-J{flag}" for flag in ENCODING_FLAGS), "--release", "17",
         "-encoding", "UTF-8", "-d", str(root), source],
        [java, *JVM_FLAGS, *ENCODING_FLAGS, "-cp", str(root), "Main"],
    )
