from acm_agent.tools.cpp_tools import compile_cpp, run_cpp


def test_compile_and_run_valid_program():
    result = compile_cpp('#include <iostream>\nint main(){std::cout << "ok\\n";}')
    assert result["status"] == "COMPILE_OK"
    ran = run_cpp(result["executable"])
    assert ran["status"] == "OK"
    assert ran["stdout"].strip() == "ok"


def test_compile_invalid_program():
    result = compile_cpp("int main( {")
    assert result["status"] == "COMPILE_ERROR"
    assert result["stderr"]


def test_runtime_error_and_timeout():
    crash = compile_cpp("int main(){return 3;}")
    assert run_cpp(crash["executable"])["status"] == "RUNTIME_ERROR"
    loop = compile_cpp("int main(){for(;;){} }")
    assert run_cpp(loop["executable"], timeout=0.2)["status"] == "TIME_LIMIT_EXCEEDED"
