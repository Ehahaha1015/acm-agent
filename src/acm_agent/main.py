from __future__ import annotations

import asyncio

from acm_agent.agents.coach import Coach, ModelUnavailable
from acm_agent.textutil import configure_stdio

BANNER = (
    "ACM Coach\n"
    "Type 'exit' to quit, '/paste' for multi-line content (terminate with /end)."
)


def _answer(coach: Coach, message: str) -> str:
    """Run one turn through the hosted model, degrading to verified local facts."""
    try:
        answer, _ = asyncio.run(coach.chat_async(message))
    except ModelUnavailable as exc:
        if exc.tool_result:
            return (
                f"{exc.local_answer}\n\n"
                f"(model unavailable: {exc.reason}; showing the verified local result)"
            )
        return f"Model unavailable: {exc.reason}"
    except KeyboardInterrupt:
        raise
    return answer.strip() or "(the model returned an empty response)"


def main() -> None:
    configure_stdio()
    print(BANNER)
    coach = Coach()
    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.strip().lower() in {"exit", "quit", "/exit", "/quit"}:
            break
        if line.strip().lower() == "/paste":
            lines: list[str] = []
            while True:
                try:
                    item = input()
                except (EOFError, KeyboardInterrupt):
                    item = "/end"
                if item.strip() == "/end":
                    break
                lines.append(item)
            message = "\n".join(lines)
        else:
            message = line
        if not message.strip():
            continue
        try:
            print(_answer(coach, message))
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue


if __name__ == "__main__":
    main()
