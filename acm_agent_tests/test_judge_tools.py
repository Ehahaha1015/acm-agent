from acm_agent.tools.judge_tools import compare_cpp, judge_cpp


def test_judge_and_whitespace_normalization():
    code = '#include <iostream>\nint main(){int x;std::cin>>x;std::cout<<x<<"   \\n";}'
    assert judge_cpp(code, "7\n")["status"] == "OK"
    other = '#include <iostream>\nint main(){int x;std::cin>>x;std::cout<<x+1;}'
    result = compare_cpp(other, code, ["7\n"])
    assert result["status"] == "WRONG_ANSWER_FOUND"
    assert result["test_number"] == 1


def test_compare_compile_error():
    good = "int main(){return 0;}"
    result = compare_cpp("int main({", good, [""])
    assert result["status"] == "CANDIDATE_COMPILE_ERROR"
