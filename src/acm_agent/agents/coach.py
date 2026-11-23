"""Orchestrator and optional OpenAI Agents SDK integration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from acm_agent.config import get_settings
from acm_agent.execution.languages import normalize_language
from acm_agent.privacy import redact_secrets
from acm_agent.textutil import sanitize_text
from acm_agent.tools import check_code, compare_code, run_code, stress_code
from acm_agent.tools.sdk_tools import (
    compare_code_tool,
    compare_cpp_tool,
    compile_code_tool,
    compile_cpp_tool,
    judge_cpp_tool,
    run_code_tool,
    run_cpp_tool,
    stress_code_tool,
    stress_cpp_tool,
)

logger = logging.getLogger(__name__)

INSTRUCTIONS = """You are ACM Coach. Explain algorithms, complexity and edge cases in
C++20, C17, Python3 and Java17. Use compile_code/run_code/compare_code/stress_code and
set the language explicitly. Candidate, reference and generator may use different languages.
Java submissions must use class Main without a package; Python runs with the standard library.
Reply in the user's language. Separate reasoning from observed execution evidence.
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
        programs = _extract_programs(message)
        candidate = programs[0] if programs else None
        reference = programs[1] if len(programs) > 1 else None
        generator = programs[2] if len(programs) > 2 else None
        input_data = _extract_input(message)
        tool_result = None
        if candidate and reference and generator:
            tool_result = stress_code(candidate[0], reference[0], generator[0],
                                      language=candidate[1], reference_language=reference[1],
                                      generator_language=generator[1], budget_seconds=30.0)
        elif candidate and reference:
            cases = _extract_cases(message)
            tool_result = compare_code(candidate[0], reference[0], cases, language=candidate[1],
                                       reference_language=reference[1], budget_seconds=30.0) if cases else None
        elif candidate and input_data is not None:
            tool_result = run_code(candidate[0], input_data, language=candidate[1])
        elif candidate and any(word in message.lower() for word in ("compile", "编译")):
            tool_result = check_code(candidate[0], language=candidate[1])
        elif candidate and any(word in message.lower() for word in ("运行", "run", "execute")):
            tool_result = run_code(candidate[0], "", language=candidate[1])
        if tool_result:
            return _format_tool_result(tool_result), tool_result
        return (
            "当前为离线工具模式，算法讲解需要配置模型。你仍可在「代码验证」中直接编译、"
            "运行、差分测试和随机对拍。支持 C++、C、Python、Java 的带语言标记代码块。"
        ), None


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

        from agents import ModelSettings, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
        from openai import AsyncOpenAI

        # Third-party OpenAI-compatible gateways usually cannot receive OpenAI tracing.
        set_tracing_disabled(True)
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            timeout=45.0,
            max_retries=0,
        )
        try:
            model = OpenAIChatCompletionsModel(
                model=settings.openai_model or "", openai_client=client
            )
            agent = self.build_sdk_agent(
                model=model, strict_tools=not settings.is_deepseek,
                model_settings=ModelSettings(
                    max_tokens=4096,
                    extra_body={"thinking": {"type": "disabled"}} if settings.is_deepseek else None,
                ),
            )
            prompt = _prompt_with_history(message, history or [], verified_tool_result)
            async with asyncio.timeout(60.0):
                result = await Runner.run(agent, prompt, max_turns=8)
        except Exception as exc:  # noqa: BLE001 - sanitize errors at the provider boundary
            reason = redact_secrets(str(exc), settings.openai_api_key)
            logger.warning("model call failed: %s", reason)
            raise ModelUnavailable(reason, local_answer, verified_tool_result) from None
        finally:
            await client.close()
        answer = str(result.final_output or "").strip()
        tool_result = _extract_sdk_tool_result(result.new_items) or verified_tool_result
        # Some OpenAI-compatible gateways accept ordinary chat completions but silently
        # drop function calls. Never show a blank response: run the local deterministic
        # router so an explicit compile/judge request still executes the real tool.
        if not answer and tool_result is None:
            return local_answer, verified_tool_result
        return answer or _format_tool_result(tool_result), tool_result

    @staticmethod
    def registered_tools() -> dict[str, object]:
        """Tool registry consumed by an OpenAI Agents SDK ``Agent`` when configured.

        The SDK builds a JSON schema per signature, so these are the JSON-safe wrappers
        from :mod:`acm_agent.tools.sdk_tools`, not the internal tools with observers.
        """
        return {
            "compile_code": compile_code_tool, "run_code": run_code_tool,
            "compare_code": compare_code_tool, "stress_code": stress_code_tool,
            "compile_cpp": compile_cpp_tool,
            "run_cpp": run_cpp_tool,
            "judge_cpp": judge_cpp_tool,
            "compare_cpp": compare_cpp_tool,
            "stress_cpp": stress_cpp_tool,
        }

    @staticmethod
    def build_sdk_agent(
        model: object | None = None, *, strict_tools: bool = True, model_settings=None
    ):
        """Construct an OpenAI Agents SDK agent when that optional dependency is installed."""
        try:
            from agents import Agent, ModelSettings, function_tool
        except ImportError as exc:
            raise RuntimeError("Install openai-agents to enable hosted LLM orchestration") from exc
        tools = [
            function_tool(fn, name_override=name, strict_mode=strict_tools)
            for name, fn in Coach.registered_tools().items()
        ]
        return Agent(
            name="ACM Coach", instructions=INSTRUCTIONS, tools=tools, model=model,
            model_settings=model_settings or ModelSettings(),
        )


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
            "A local program tool has already executed. Treat this JSON as the verified result, "
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
    blocks = [code for code, language in _extract_programs(message)]
    return tuple((blocks + [None, None, None])[:3])


def _extract_programs(message: str) -> list[tuple[str, str]]:
    programs = []
    for match in re.finditer(r"```([^\n`]*)\n?(.*?)```", message, re.DOTALL):
        language, body = match.group(1).strip().lower(), match.group(2)
        try:
            detected = normalize_language(language)
        except ValueError:
            if language or not ("#include" in body or "int main" in body):
                continue
            detected = "cpp"
        programs.append((body, detected))
    return programs


def _extract_input(message: str) -> str | None:
    match = re.search(
        r"(?:input|输入)\s*[:：]?\s*```[^\n`]*\n(.*?)```",
        message, re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else None


def _extract_cases(message: str) -> list[str]:
    text = _extract_input(message)
    return [text] if text is not None else []


def _format_tool_result(result: dict) -> str:
    status = result.get("status", "UNKNOWN")
    if status == "WRONG_ANSWER_FOUND":
        return f"{status}: seed/test {result.get('seed', result.get('test_number'))}\nInput:\n{result.get('input')}\nCandidate:\n{result.get('candidate_output')}\nReference:\n{result.get('reference_output')}"
    parts = [f"Tool result: {status}."]
    if result.get("stdout"):
        parts.append(f"标准输出：\n```text\n{result['stdout']}\n```")
    if result.get("stderr"):
        parts.append(f"诊断信息：\n```text\n{result['stderr']}\n```")
    if result.get("warning"):
        parts.append(result["warning"])
    return "\n\n".join(parts)
