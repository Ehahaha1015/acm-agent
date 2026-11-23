from __future__ import annotations

import argparse
import asyncio
import json

from acm_agent.agents.coach import Coach, ModelUnavailable
from acm_agent.config import get_settings
from acm_agent.diagnostics import runtime_status
from acm_agent.execution.backend import reset_backend
from acm_agent.memory.session import SessionStore
from acm_agent.textutil import configure_stdio

BANNER = (
    "ACM Coach\n"
    "Type 'exit' to quit, '/paste' for multi-line content (terminate with /end)."
)


def _answer(coach: Coach, message: str, history: list[dict] | None = None) -> str:
    """Run one turn through the hosted model, degrading to verified local facts."""
    try:
        answer, _ = asyncio.run(coach.chat_async(message, history))
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
    parser = argparse.ArgumentParser(description="ACM Agent · C++ / C / Python / Java 算法教练")
    parser.add_argument("--web", action="store_true", help="启动浏览器工作台")
    parser.add_argument("--host", default="127.0.0.1", help="Web 监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--doctor", action="store_true", help="检查运行环境，不输出密钥")
    parser.add_argument("--session", help="继续已有的 CLI 或 Web 会话")
    args = parser.parse_args()
    if args.doctor:
        print(json.dumps(runtime_status(), ensure_ascii=False, indent=2))
        return
    if args.web:
        import uvicorn
        uvicorn.run("acm_agent.api.app:app", host=args.host, port=args.port)
        return
    store = SessionStore(get_settings().database)
    if args.session and not store.session_exists(args.session):
        parser.error("会话不存在，请在 Web 界面查看已有会话 ID")
    session_id = store.ensure_session(args.session)
    print(BANNER)
    print(f"Session: {session_id}")
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
            history = store.history(session_id)
            store.add_message(session_id, "user", message)
            answer = _answer(coach, message, history)
            store.add_message(session_id, "assistant", answer)
            print(answer)
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue
    reset_backend()


if __name__ == "__main__":
    main()
