import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acm_agent.agents.coach import Coach
from acm_agent.api.app import app
from acm_agent.execution.backend import DockerBackend
from acm_agent.tools import check_code, compare_code, run_code, stress_code

EXAMPLES = json.loads((Path(__file__).resolve().parents[1] /
                       "src/acm_agent/api/web/examples.json").read_text(encoding="utf-8"))
LANGUAGES = list(EXAMPLES)
client = TestClient(app)
INPUT = "3\n-2 -5 -1\n"


@pytest.mark.parametrize("language", LANGUAGES)
def test_real_language_program_through_http(language):
    response = client.post("/execute", json={
        "language": language, "code": EXAMPLES[language]["reference"], "input_data": INPUT,
    })
    assert response.status_code == 200
    result = response.json()
    assert result["result"]["status"] == "OK", result
    assert result["result"]["stdout"].strip() == "-1"
    assert result["languages"]["candidate"] == language


@pytest.mark.parametrize("language,code", [
    ("cpp", "int main( {"), ("c", "int main( {"),
    ("python", "if :\n  pass"), ("java", "public class Main { invalid }"),
])
def test_real_syntax_or_compile_diagnostics(language, code):
    result = check_code(code, language=language)
    assert result["status"] == "COMPILE_ERROR"
    assert result["stderr"]
    assert "executable" not in result
    assert "run_command" not in result


def test_python_check_never_executes_top_level_code():
    code = "raise RuntimeError('runtime only')"
    assert check_code(code, language="python")["status"] == "COMPILE_OK"
    ran = run_code(code, "", language="python")
    assert ran["status"] == "RUNTIME_ERROR"
    assert "runtime only" in ran["stderr"]


@pytest.mark.parametrize("language,code", [
    ("cpp", '#include <iostream>\nint main(){std::cout<<"你好 ACM";}'),
    ("c", '#include <stdio.h>\nint main(void){printf("你好 ACM");}'),
    ("python", "print('你好 ACM')"),
    ("java", 'public class Main {public static void main(String[] a){System.out.print("你好 ACM");}}'),
])
def test_empty_stdin_and_utf8_output(language, code):
    result = run_code(code, "", language=language)
    assert result["status"] == "OK", result
    assert result["stdout"].strip() == "你好 ACM"


@pytest.mark.parametrize("language,code", [
    ("cpp", "int main(){return 9;}"), ("c", "int main(void){return 9;}"),
    ("python", "raise SystemExit(9)"),
    ("java", "public class Main {public static void main(String[] a){System.exit(9);}}"),
])
def test_runtime_exit_code_is_preserved(language, code):
    result = run_code(code, "", language=language)
    assert result["status"] == "RUNTIME_ERROR", result
    assert result["exit_code"] == 9


@pytest.mark.parametrize("language,code", [
    ("cpp", "int main(){for(;;){}}"), ("c", "int main(void){for(;;){}}"),
    ("python", "while True: pass"),
    ("java", "public class Main {public static void main(String[] a){while(true){}}}"),
])
def test_timeout_is_enforced_for_every_language(language, code):
    result = run_code(code, "", language=language, timeout=0.2)
    assert result["status"] == "TIME_LIMIT_EXCEEDED", result
    assert result["timed_out"]


@pytest.mark.parametrize("language,code", [
    ("cpp", '#include <cstdio>\nint main(){for(;;) puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}'),
    ("c", '#include <stdio.h>\nint main(void){for(;;) puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}'),
    ("python", "import sys\nwhile True: sys.stdout.write('x'*8192); sys.stdout.flush()"),
    ("java", 'public class Main {public static void main(String[] a){while(true) System.out.print("x".repeat(8192));}}'),
])
def test_output_limit_is_enforced_for_every_language(language, code):
    result = run_code(code, "", language=language, timeout=5)
    assert result["status"] == "OUTPUT_LIMIT_EXCEEDED", result["status"]
    assert len(result["stdout"]) <= 1_048_576


@pytest.mark.parametrize("language", LANGUAGES)
def test_stress_counterexample_replays_in_explicit_compare(language):
    example = EXAMPLES[language]
    result = stress_code(example["candidate"], example["reference"], example["generator"],
                         language=language, iterations=1, start_seed=1)
    assert result["status"] == "WRONG_ANSWER_FOUND", result
    assert result["seed"] == 1
    assert result["candidate_output"].strip() == "0"
    replay = compare_code(example["candidate"], example["reference"], [result["input"]], language=language)
    assert replay["status"] == "WRONG_ANSWER_FOUND"
    assert replay["candidate_output"] == result["candidate_output"]
    assert replay["reference_output"] == result["reference_output"]


def test_mixed_language_stress_through_http():
    response = client.post("/execute", json={
        "mode": "stress", "language": "c", "reference_language": "java",
        "generator_language": "python", "code": EXAMPLES["c"]["candidate"],
        "reference_code": EXAMPLES["java"]["reference"],
        "generator_code": EXAMPLES["python"]["generator"], "iterations": 1,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["status"] == "WRONG_ANSWER_FOUND", payload
    assert payload["languages"] == {"candidate": "c", "reference": "java", "generator": "python"}
    assert payload["result"]["reference_output"].strip() == "-10"


@pytest.mark.parametrize("language", ["python", "c", "java"])
def test_offline_chat_routes_labeled_code_without_mistaking_stdin(language):
    message = f"请运行\n```{language}\n{EXAMPLES[language]['reference']}\n```\n输入：```text\n{INPUT}```"
    answer, result = Coach().chat(message)
    assert result["status"] == "OK", result
    assert result["language"] == language
    assert result["stdout"].strip() == "-1"
    assert "-1" in answer


@pytest.mark.parametrize("field", ["language", "reference_language", "generator_language"])
def test_http_rejects_unknown_languages(field):
    assert client.post("/execute", json={"code": "print(1)", field: "shell"}).status_code == 422


def test_missing_toolchain_is_not_reported_as_bad_source(monkeypatch):
    monkeypatch.setenv("ACM_JAVAC", "missing-acm-javac-compiler")
    result = run_code(EXAMPLES["java"]["reference"], INPUT, language="java")
    assert result["status"] == "TOOLCHAIN_UNAVAILABLE"
    assert client.get("/status").json()["runtimes"]["java"]["available"] is False


@pytest.mark.parametrize("language", LANGUAGES)
def test_docker_uses_correct_language_commands_and_paths(language):
    scripts = []

    def runner(argv, input_text="", timeout=120):
        if argv[1] == "run":
            return 0, "worker\n", "", False
        if argv[1] == "inspect":
            return 0, "true\n", "", False
        scripts.append(argv[-1])
        return 0, "-1\n" if "cat >" not in argv[-1] else "", "", False

    engine = DockerBackend(workers=1, runner=runner)
    with engine.workspace() as workspace:
        compiled = engine.compile(workspace, EXAMPLES[language]["reference"], language=language)
        result = engine.run(workspace, compiled, INPUT)
    assert result.status == "OK"
    compile_script, run_script = scripts[:2]
    expected = {"cpp": "g++", "c": "gcc", "python": "py_compile", "java": "javac"}
    assert expected[language] in compile_script
    assert "/tmp/acm-agent/" in run_script
    if language == "java":
        assert "-cp" in run_script and run_script.endswith(" Main")
    if language == "python":
        assert "python3 -I -X utf8" in run_script
    engine.close()
