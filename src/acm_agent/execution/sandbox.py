"""Compatibility adapter using the shared, bounded multi-language Docker backend."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from acm_agent.config import get_settings
from acm_agent.execution.backend import DockerBackend


@dataclass(slots=True)
class DockerExecutor:
    image: str = "acm-agent-runtime:latest"
    memory: str = "512m"
    cpus: str = "1.0"
    timeout: float = 2.0

    def run(self, source: str, input_data: str = "", language: str = "cpp") -> subprocess.CompletedProcess[str]:
        engine = DockerBackend(image=self.image, workers=1, memory=self.memory, cpus=self.cpus)
        try:
            with engine.workspace() as workspace:
                compiled = engine.compile(workspace, source, timeout=get_settings().compile_timeout,
                                          language=language)
                if compiled.status != "COMPILE_OK":
                    return subprocess.CompletedProcess(compiled.command or [],
                                                       compiled.exit_code or 1,
                                                       compiled.stdout, compiled.stderr)
                ran = engine.run(workspace, compiled, input_data, timeout=self.timeout)
                return subprocess.CompletedProcess(compiled.run_command or [],
                                                   ran.exit_code if ran.exit_code is not None else 124,
                                                   ran.stdout, ran.stderr)
        finally:
            engine.close()
