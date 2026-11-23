"""Exercise the shipped examples against real local or Docker language toolchains."""

import argparse
import json
from pathlib import Path

from acm_agent.config import get_settings
from acm_agent.execution.backend import DockerBackend, LocalBackend, reset_backend, set_backend
from acm_agent.tools import run_code, stress_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executor", choices=["local", "docker"], default="local")
    args = parser.parse_args()
    examples = json.loads((Path(__file__).resolve().parents[1] /
                           "src/acm_agent/api/web/examples.json").read_text(encoding="utf-8"))
    engine = DockerBackend(image=get_settings().docker_image) if args.executor == "docker" else LocalBackend()
    set_backend(engine)
    try:
        for language, example in examples.items():
            run = run_code(example["reference"], "3\n-2 -5 -1\n", language=language)
            assert run["status"] == "OK" and run["stdout"].strip() == "-1", run
            stress = stress_code(example["candidate"], example["reference"], example["generator"],
                                 language=language, iterations=1, start_seed=1, budget_seconds=30)
            assert stress["status"] == "WRONG_ANSWER_FOUND" and stress["seed"] == 1, stress
            print(json.dumps({"executor": args.executor, "language": language,
                              "run": run["status"], "stdout": run["stdout"].strip(),
                              "stress": stress["status"], "seed": stress["seed"]}), flush=True)
    finally:
        reset_backend()


if __name__ == "__main__":
    main()
