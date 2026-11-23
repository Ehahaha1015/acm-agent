from __future__ import annotations


class ReviewerAgent:
    instructions = "Review C++20, C17, Python3 and Java17 for correctness, overflow, indexing, complexity and WA/TLE/RE risks."

    def analyze(self, code: str) -> str:
        return "Use compile_code or run_code with an explicit language to validate execution claims."
