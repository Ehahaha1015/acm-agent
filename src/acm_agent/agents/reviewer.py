from __future__ import annotations


class ReviewerAgent:
    instructions = "Review C++20 for correctness, overflow, indexing, complexity, WA/TLE/RE risks."

    def analyze(self, code: str) -> str:
        return "Use compile_cpp or judge_cpp to validate claims about this code."
