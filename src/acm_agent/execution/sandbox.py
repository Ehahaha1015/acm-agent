"""Docker execution abstraction. Local subprocess remains explicitly trusted-only."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DockerExecutor:
    image: str = "gcc:14"
    memory: str = "256m"
    cpus: str = "1.0"
    timeout: float = 2.0

    def run(self, source: str, input_data: str = "") -> subprocess.CompletedProcess[str]:
        # Mount only two temporary files; the container has no network and no write access
        # outside its ephemeral /tmp. This keeps source and test input out of the command line.
        with tempfile.TemporaryDirectory(prefix="acm-docker-") as directory:
            root = Path(directory)
            (root / "main.cpp").write_text(source, encoding="utf-8")
            (root / "input.txt").write_text(input_data, encoding="utf-8")
            command = [
                "docker", "run", "--rm", "--network=none", "--read-only", "--pids-limit=64",
                f"--memory={self.memory}", f"--cpus={self.cpus}", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,size=64m", "-v", f"{root}:/work:ro", "-i", self.image,
                "sh", "-c", "g++ /work/main.cpp -std=c++20 -O2 -o /tmp/main && /tmp/main < /work/input.txt",
            ]
            return subprocess.run(command, text=True, capture_output=True, timeout=self.timeout, check=False)
