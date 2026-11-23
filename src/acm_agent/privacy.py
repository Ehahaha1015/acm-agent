"""Prevent provider errors from reflecting credentials into responses or logs."""

import re


def redact_secrets(text: str, secret: str | None = None) -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s'\"<>,;]+", "Bearer [REDACTED]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
