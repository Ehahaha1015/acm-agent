from __future__ import annotations


class TesterAgent:
    instructions = "Design edge cases and use compare_cpp/stress_cpp; report reproducible seeds."

    def analyze(self, request: str) -> str:
        return "Supply candidate, reference, and optionally a generator for differential testing."
