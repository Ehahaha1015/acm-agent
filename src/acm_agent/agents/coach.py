"""Orchestrator and optional OpenAI Agents SDK integration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from acm_agent.config import get_settings
from acm_agent.textutil import sanitize_text
from acm_agent.tools import compare_cpp, compile_cpp, judge_cpp, stress_cpp
from acm_agent.tools.sdk_tools import (
    compare_cpp_tool,
    compile_cpp_tool,
    judge_cpp_tool,
    run_cpp_tool,
    stress_cpp_tool,
)

logger = logging.getLogger(__name__)

INSTRUCTIONS = """You are ACM Coach. Explain algorithms, complexity, edge cases and C++20.
Use tools whenever execution is requested or source and input are supplied. Never claim a
program compiled, ran, timed out, or had a counterexample unless a tool returned that fact.
Passing finite or random tests is evidence, not a proof of correctness."""


class ModelUnavailable(RuntimeError):
    """The hosted model could not be reached.

    Verified local execution results may still exist, so the caller can degrade to them
    instead of showing the user an empty failure.
    """

    def __init__(self, reason: str, local_answer: str, tool_result: dict | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.local_answer = local_answer
        self.tool_result = tool_result


@dataclass
class CoachEngine:
    """Deterministic local engine; no API key is required for tests and offline use."""

    def answer(self, message: str) -> tuple[str, dict | None]:
        candidate, reference, generator = _extract_blocks(message)
        tool_result = None
        if candidate and reference and generator:
            tool_result = stress_cpp(candidate, reference, generator)
        elif candidate and reference:
            cases = _extract_cases(message)
            tool_result = compare_cpp(candidate, reference, cases) if cases else None
        elif candidate and _extract_input(message):
            tool_result = judge_cpp(candidate, _extract_input(message))
        elif candidate and any(word in message.lower() for word in ("compile", "编译")):
            tool_result = compile_cpp(candidate)
        if tool_result:
            return _format_tool_result(tool_result), tool_result
        return ("I can analyze the algorithm, complexity, invariants, edge cases, and C++20 code. "
                "Provide source plus input/reference when you want real execution."), None


class Coach:
    """Public facade. The Agents SDK can be plugged in without changing tool semantics."""

    def __init__(self) -> None:
        self.engine = CoachEngine()

    def chat(self, message: str) -> tuple[str, dict | None]:
        return self.engine.answer(sanitize_text(message))

    async def chat_async(
        self, message: str, history: list[dict[str, str]] | None = None
    ) -> tuple[str, dict | None]:
        """Run the real model/tool loop when configured, otherwise use the offline engine."""
        # Text arriving from a terminal, a pipe or a JSON escape can carry lone surrogates,
        # which cannot be encoded as UTF-8 and would fail deep inside the request body.
        message = sanitize_text(message)
        history = [
            {
                "role": str(item.get("role", "user")),
                "content": sanitize_text(str(item.get("content", ""))),
            }
            for item in (history or [])
        ]
        # Compilation and execution are blocking operations; keep FastAPI's event loop free.
        local_answer, verified_tool_result = await asyncio.to_thread(self.chat, message)
        settings = get_settings()
        if not settings.llm_configured:
            return local_answer, verified_tool_result

        from agents import OpenAIChatCompletionsModel, Runner, set_tracing_disabled
        from openai import AsyncOpenAI

        # Third-party OpenAI-compatible gateways usually cannot receive OpenAI tracing.
        set_tracing_disabled(bool(settings.openai_base_url))
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            timeout=60.0,
        )
        model = OpenAIChatCompletionsModel(
            model=settings.openai_model or "",
            openai_client=client,
        )
        agent = self.build_sdk_agent(model=model)
        prompt = _prompt_with_history(message, history or [], verified_tool_result)
        try:
            result = await Runner.run(agent, prompt, max_turns=8)
        except Exception as exc:
            logger.warning("model call failed: %s", exc)
            raise ModelUnavailable(str(exc), local_answer, verified_tool_result) from exc
        finally:
            await client.close()
        answer = str(result.final_output or "").strip()
        tool_result = _extract_sdk_tool_result(result.new_items) or verified_tool_result
        # Some OpenAI-compatible gateways accept ordinary chat completions but silently
        # drop function calls. Never show a blank response: run the local deterministic
        # router so an explicit compile/judge request still executes the real tool.
        if not answer and tool_result is None:
            return local_answer, verified_tool_result
        return answer, tool_result

    @staticmethod
    def registered_tools() -> dict[str, object]:
        """Tool registry consumed by an OpenAI Agents SDK ``Agent`` when configured.

        The SDK builds a JSON schema per signature, so these are the JSON-safe wrappers
        from :mod:`acm_agent.tools.sdk_tools`, not the internal tools with observers.
        """
        return {
            "compile_cpp": compile_cpp_tool,
            "run_cpp": run_cpp_tool,
            "judge_cpp": judge_cpp_tool,
            "compare_cpp": compare_cpp_tool,
            "stress_cpp": stress_cpp_tool,
        }

    @staticmethod
    def build_sdk_agent(model: object | None = None):
        """Construct an OpenAI Agents SDK agent when that optional dependency is installed."""
        try:
            from agents import Agent, function_tool
        except ImportError as exc:
            raise RuntimeError("Install openai-agents to enable hosted LLM orchestration") from exc
        tools = [
            function_tool(fn, name_override=name)
            for name, fn in Coach.registered_tools().items()
        ]
        return Agent(name="ACM Coach", instructions=INSTRUCTIONS, tools=tools, model=model)


def _prompt_with_history(
    message: str, history: list[dict[str, str]], verified_tool_result: dict | None = None
) -> str:
    recent = history[-12:]
    parts: list[str] = []
    if recent:
        transcript = "\n".join(f"{item['role']}: {item['content']}" for item in recent)
        parts.append(f"Previous conversation:\n{transcript}")
    parts.append(f"Current user message:\n{message}")
    if verified_tool_result:
        parts.append(
            "A local C++ tool has already executed. Treat this JSON as the verified result, "
            "explain it clearly, and never contradict or invent execution facts:\n"
            + json.dumps(verified_tool_result, ensure_ascii=False)
        )
    return "\n\n".join(parts)


def _extract_sdk_tool_result(items: list[Any]) -> dict | None:
    for item in reversed(items):
        if getattr(item, "type", None) != "tool_call_output_item":
            continue
        output = getattr(item, "output", None)
        if isinstance(output, dict):
            return output
        if isinstance(output, str):
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _extract_blocks(message: str) -> tuple[str | None, str | None, str | None]:
    code_blocks: list[str] = []
    for match in re.finditer(r"```([^\n`]*)\n?(.*?)```", message, re.DOTALL):
        language, body = match.group(1).strip().lower(), match.group(2)
        looks_like_cpp = language in {"cpp", "c++", "cc", "cxx"} or "#include" in body or "int main" in body
        if looks_like_cpp:
            code_blocks.append(body)
    candidate = code_blocks[0] if code_blocks else None
    reference = code_blocks[1] if len(code_blocks) > 1 else None
    generator = code_blocks[2] if len(code_blocks) > 2 else None
    return candidate, reference, generator


def _extract_input(message: str) -> str | None:
    match = re.search(r"(?:input|输入)\s*[:：]\s*```?\s*([^`]+?)\s*```?(?:\n|$)", message, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _extract_cases(message: str) -> list[str]:
    text = _extract_input(message)
    return [text] if text else []


def _format_tool_result(result: dict) -> str:
    status = result.get("status", "UNKNOWN")
    if status == "WRONG_ANSWER_FOUND":
        return f"{status}: seed/test {result.get('seed', result.get('test_number'))}\nInput:\n{result.get('input')}\nCandidate:\n{result.get('candidate_output')}\nReference:\n{result.get('reference_output')}"
    return f"Tool result: {status}. {result.get('warning', '')}".strip()
