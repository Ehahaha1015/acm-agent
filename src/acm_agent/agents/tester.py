from __future__ import annotations


class TesterAgent:
    instructions = "Design edge cases and use compare_code/stress_code in cpp/c/python/java; report reproducible seeds and languages."

    def analyze(self, request: str) -> str:
        return "Supply candidate, reference, and optionally a generator for differential testing."
