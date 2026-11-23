import asyncio
import sqlite3
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from acm_agent.agents.coach import Coach
from acm_agent.api.app import app
from acm_agent.execution.backend import DockerBackend, LocalBackend, set_backend
from acm_agent.execution.executor import MAX_CAPTURE, OUTPUT_LIMIT_EXIT_CODE, run_command
from acm_agent.memory.session import SessionStore
from acm_agent.tools.judge_tools import compare_cpp
from acm_agent.tools.sdk_tools import compile_cpp_tool, run_cpp_tool
from acm_agent.tools.stress_tools import stress_cpp

client = TestClient(app)
HELLO = '#include <iostream>\nint main(){std::cout << "hello";}'


def test_run_without_stdin_and_return_trace():
    response = client.post("/execute", json={"code": HELLO})
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["status"] == "OK"
    assert payload["result"]["stdout"] == "hello"
    assert [event["stage"] for event in payload["trace"]] == ["compile", "run", "ran"]


def test_compile_checks_clean_temporary_workspace(tmp_path, monkeypatch):
    engine = LocalBackend()
    monkeypatch.setattr("acm_agent.tools.cpp_tools.backend", lambda: engine)
    result = client.post("/execute", json={"mode": "compile", "code": "int main(){}"})
    assert result.json()["result"]["status"] == "COMPILE_OK"
    assert "executable" not in result.json()["result"]
    assert not engine._roots


@pytest.mark.parametrize("payload", [
    {"code": " "}, {"code": HELLO, "mode": "unknown"},
    {"code": HELLO, "mode": "compare"},
    {"code": HELLO, "mode": "stress", "reference_code": HELLO},
    {"code": HELLO, "iterations": 0}, {"code": HELLO, "iterations": 1001},
    {"code": HELLO, "timeout": 0}, {"code": HELLO, "timeout": 11},
    {"code": HELLO, "test_cases": ["x" * 100_001]},
])
def test_execute_rejects_invalid_requests(payload):
    assert client.post("/execute", json=payload).status_code == 422


def test_empty_compare_is_never_reported_as_passed():
    assert compare_cpp(HELLO, HELLO, [])["status"] == "INVALID_TEST_CASES"


def test_chat_empty_input_and_language_tag_preserves_whitespace():
    answer, result = Coach().chat(f"```cpp\n{HELLO}\n```\n输入：```text\n\n```\n")
    assert result["status"] == "OK"
    assert "hello" in answer


def test_session_results_survive_restore_and_delete(monkeypatch):
    async def answer(message, history):
        return "observed hello", {"status": "OK", "stdout": "hello"}

    monkeypatch.setattr("acm_agent.api.app.coach.chat_async", answer)
    payload = client.post("/chat", json={"message": "first question"}).json()
    sid = payload["session_id"]
    assert client.get("/sessions").json()["sessions"][0]["title"] == "first question"
    restored = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert restored[-1]["tool_result"]["stdout"] == "hello"
    assert client.delete(f"/sessions/{sid}").status_code == 200
    assert client.get(f"/sessions/{sid}/messages").status_code == 404
    assert client.get("/sessions").json()["sessions"] == []
    assert client.post("/chat", json={"message": "next", "session_id": sid}).status_code == 404


def test_legacy_database_migration_keeps_messages(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY, created_at TEXT)")
        db.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT)")
        db.execute("INSERT INTO sessions VALUES ('old', '2026-01-01')")
        db.execute("INSERT INTO messages VALUES (1, 'old', 'user', 'saved')")
    store = SessionStore(path)
    assert store.history("old") == [{"role": "user", "content": "saved"}]
    store.add_message("old", "assistant", "ok", {"status": "OK"})
    assert store.history("old")[-1]["tool_result"] == {"status": "OK"}


def test_noisy_process_is_stopped_with_bounded_capture():
    stdout, _stderr, code, timed_out, _ = run_command(
        [sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x'*8192); sys.stdout.flush()"],
        timeout=5,
    )
    assert code == OUTPUT_LIMIT_EXIT_CODE
    assert len(stdout) <= MAX_CAPTURE
    assert not timed_out


def test_status_never_exposes_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    response = client.get("/status")
    assert response.json()["model_configured"] is True
    assert "secret-value" not in response.text


def test_docker_stress_works_with_one_worker_and_correct_executable_path():
    calls = []

    def runner(argv, input_text="", timeout=120):
        calls.append(argv)
        if argv[1] == "run":
            return 0, "worker\n", "", False
        if argv[1] == "inspect":
            return 0, "true\n", "", False
        script = argv[-1]
        if "timeout -s KILL" in script and "g++" not in script:
            assert "/tmp/acm-agent/" in script
            if script.endswith("/2/program"):
                return 0, "3\n-2 -5 -1\n", "", False
            return 0, "0" if script.endswith("/0/program") else "-1", "", False
        return 0, "", "", False

    engine = DockerBackend(workers=1, runner=runner)
    set_backend(engine)
    try:
        result = stress_cpp(HELLO, HELLO, HELLO, iterations=1)
        assert result["status"] == "WRONG_ANSWER_FOUND"
        assert result["seed"] == 1
        assert sum(call[1] == "run" for call in calls) == 1
    finally:
        set_backend(None)
        engine.close()


def test_sdk_tools_honor_selected_backend(monkeypatch):
    class OfflineDocker:
        def workspace(self):
            from acm_agent.execution.backend import BackendUnavailable
            raise BackendUnavailable("docker unavailable")

    set_backend(OfflineDocker())
    try:
        assert asyncio.run(compile_cpp_tool(HELLO))["status"] == "SANDBOX_UNAVAILABLE"
        assert asyncio.run(run_cpp_tool(HELLO))["status"] == "SANDBOX_UNAVAILABLE"
    finally:
        set_backend(None)


def test_sdk_agent_tool_schemas_are_valid():
    agent = Coach.build_sdk_agent(model="test-model")
    assert {tool.name for tool in agent.tools} == {
        "compile_cpp", "run_cpp", "judge_cpp", "compare_cpp", "stress_cpp",
        "compile_code", "run_code", "compare_code", "stress_code",
    }


def test_model_failure_keeps_verified_local_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    async def unavailable(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("agents.Runner.run", unavailable)
    monkeypatch.setattr(Coach, "chat", lambda self, message: ("verified", {"status": "OK"}))
    response = client.post("/chat", json={"message": "run my code"})
    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["answer"] == "verified"
    assert response.json()["tool_result"] == {"status": "OK"}


def test_empty_model_answer_still_shows_tool_output(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    async def blank(*args, **kwargs):
        return SimpleNamespace(final_output="", new_items=[])

    monkeypatch.setattr("agents.Runner.run", blank)
    monkeypatch.setattr(Coach, "chat", lambda self, message: ("verified", {"status": "OK", "stdout": "hello"}))
    answer, result = asyncio.run(Coach().chat_async("run my code"))
    assert "hello" in answer
    assert result["status"] == "OK"
