import os

from dotenv import load_dotenv

from agents import (
    Agent,
    Runner,
    set_default_openai_api,
    set_tracing_disabled,
)

from acm_agent.tools.cpp_tools import (
    compile_cpp,
    run_cpp,
)


def read_user_input() -> str:
    first_line = input("You > ").strip()

    if first_line != "/paste":
        return first_line

    print("\nPaste your multi-line content.")
    print("Type /end on a NEW LINE when finished.\n")

    lines: list[str] = []

    while True:
        line = input()

        if line.strip() == "/end":
            break

        lines.append(line)

    return "\n".join(lines)


def main() -> None:
    load_dotenv()

    # 你的第三方 OpenAI-compatible 中转站
    set_default_openai_api("chat_completions")

    # 不上传 OpenAI 官方 tracing
    set_tracing_disabled(True)

    coach = Agent(
        name="ACM Coach",
        model=os.environ["OPENAI_MODEL"],
        instructions="""
You are an expert competitive programming coach.

The user is experienced with C++ and competitive programming.

You have tools that can compile and execute C++ code.

IMPORTANT TOOL RULES:

- If the user explicitly asks you to compile C++ code,
  you MUST call compile_cpp.

- If the user explicitly asks you to execute C++ code,
  you MUST first call compile_cpp.
  If compilation succeeds, call run_cpp.

- Never claim that code was compiled or executed unless
  you actually used the corresponding tool.

- If compilation fails, use the actual compiler stderr
  returned by compile_cpp to explain the exact error.

- Successful compilation does not prove algorithmic correctness.
""",
        tools=[
            compile_cpp,
            run_cpp,
        ],
    )

    print("ACM Coach")
    print("Type 'exit' to quit.")
    print("Type '/paste' to enter multi-line code.\n")

    while True:
        question = read_user_input().strip()

        if question.lower() in {"exit", "quit"}:
            print("Bye!")
            break

        if not question:
            continue

        result = Runner.run_sync(
            coach,
            question,
        )

        print("\nACM Coach >")
        print(result.final_output)
        print()


if __name__ == "__main__":
    main()
