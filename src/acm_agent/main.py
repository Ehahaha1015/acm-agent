import os

from dotenv import load_dotenv
from acm_agent.tools.judge_tools import judge_cpp

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
tools=[
    compile_cpp,
    run_cpp,
    judge_cpp,
],

def read_user_input() -> str:
    while True:
        first_line = input("You > ").strip()

        # 忽略空输入，不让主循环反复打印奇怪的提示
        if not first_line:
            continue

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

        content = "\n".join(lines).strip()

        if content:
            return content

        print("Nothing was pasted. Try again.\n")


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

Tool rules:

- If the user asks you to check whether C++ code compiles,
  use compile_cpp.

- If the user asks you to run already compiled code,
  use run_cpp.

- Prefer judge_cpp when the user provides both
  C++ source code and concrete input data.

- Never claim code was compiled or executed unless
  you actually used a tool.
""",

    tools=[
        compile_cpp,
        run_cpp,
        judge_cpp,
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
        print("\n[debug] final_output =", repr(result.final_output))
        print("[debug] new_items:")

        for item in result.new_items:
            print("  -", type(item).__name__)

        print("\nACM Coach >")

        if result.final_output:
            print(result.final_output)
        else:
            print("[no final output]")


if __name__ == "__main__":
    main()
