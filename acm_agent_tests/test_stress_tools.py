from acm_agent.tools.stress_tools import stress_cpp

GEN = r'''#include <iostream>
#include <random>
int main(){ unsigned long long s; if(!(std::cin>>s)) return 2; std::mt19937_64 g(s); std::cout<<5<<"\n"; for(int i=0;i<5;i++) std::cout << -(int)(g()%100+1) << " "; }'''
CANDIDATE = r'''#include <iostream>
int main(){int n;std::cin>>n; long long ans=0,x; while(n--){std::cin>>x;ans=std::max(ans,x);} std::cout<<ans;}'''
REFERENCE = r'''#include <iostream>
#include <climits>
int main(){int n;std::cin>>n; long long ans=LLONG_MIN,x; while(n--){std::cin>>x;ans=std::max(ans,x);} std::cout<<ans;}'''


def test_stress_finds_reproducible_negative_counterexample():
    result = stress_cpp(CANDIDATE, REFERENCE, GEN, iterations=3, start_seed=1)
    assert result["status"] == "WRONG_ANSWER_FOUND"
    assert result["seed"] == 1
    assert all(int(x) < 0 for x in result["input"].split()[1:])


def test_invalid_generator_output():
    result = stress_cpp("int main(){}", "int main(){}", "int main(){return 0;}", iterations=1)
    assert result["status"] == "GENERATOR_INVALID_OUTPUT"


def test_generator_compile_error():
    result = stress_cpp("int main(){}", "int main(){}", "int main({", iterations=1)
    assert result["status"] == "GENERATOR_COMPILE_ERROR"
