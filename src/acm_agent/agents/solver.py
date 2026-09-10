from __future__ import annotations


class SolverAgent:
    """Role definition for an Agents SDK solver sub-agent."""

    instructions = "Derive an algorithm, proof idea, and time/space complexity."

    def analyze(self, problem: str) -> str:
        return "Provide the problem statement and constraints for algorithm design."
