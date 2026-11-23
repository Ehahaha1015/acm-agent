"""Check the Git index without printing credentials or source excerpts."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def local_secrets(root: Path) -> list[bytes]:
    values = [os.getenv(name, "") for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY")]
    env_path = root / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip().endswith("API_KEY"):
                values.append(value.strip().strip("\"'"))
    return [value.encode() for value in values if len(value) >= 12 and "your_api_key" not in value.lower()]


def find_problem(path: str, content: bytes, secrets: list[bytes]) -> str | None:
    name = Path(path).name
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        return "local environment file"
    if path.startswith("secrets/") or name.endswith(".key"):
        return "credential file"
    if any(secret in content for secret in secrets):
        return "matches a locally configured API key"
    if re.search(rb"\bsk-[A-Za-z0-9_-]{20,}", content):
        return "API key pattern"
    if re.search(rb"(?m)^-----BEGIN (?:RSA )?PRIVATE KEY-----\r?$", content):
        return "private key material"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Scan every tracked file in the index")
    args = parser.parse_args()
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    os.chdir(root)
    secrets = local_secrets(root)
    listing = git("ls-files", "-z") if args.all else git(
        "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"
    )
    paths = [path.decode() for path in listing.split(b"\0") if path]
    problems = []
    for path in paths:
        reason = find_problem(path, git("show", f":{path}"), secrets)
        if reason:
            problems.append((path, reason))
    for path, reason in problems:
        print(f"BLOCKED: {path}: {reason}")
    if problems:
        print("Remove credentials from the index before committing. Secret values are not printed.")
        return 1
    print(f"Secret check passed: {len(paths)} indexed files; no credential values printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
