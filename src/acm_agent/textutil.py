"""Text handling shared by the CLI, the API and the model layer.

Windows is the reason this module exists. A console code page (``cp936``, ``cp1252``, …)
and a UTF-8 pipeline can disagree about the same bytes, which produces mojibake and even
lone surrogates. A lone surrogate cannot be encoded as UTF-8, so it would otherwise
explode deep inside an HTTP request body with a confusing "surrogates not allowed" error.
Everything that crosses a process, terminal or network boundary goes through here.
"""

from __future__ import annotations

import sys
from typing import TextIO


def sanitize_text(value: str) -> str:
    """Replace characters that cannot be encoded as UTF-8 (e.g. lone surrogates)."""
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-8", "replace").decode("utf-8")
    return value


def configure_stdio() -> None:
    """Make console output UTF-8 and make piped input deterministic.

    Output is always reconfigured: a Chinese answer must never crash on ``cp936``.
    Input is only forced to UTF-8 when it is *not* a terminal, because an interactive
    console is genuinely encoded in the active code page and re-decoding typed text as
    UTF-8 would corrupt it.
    """
    for stream in (sys.stdout, sys.stderr):
        _reconfigure(stream, encoding="utf-8", errors="replace")
    stdin = sys.stdin
    if stdin is not None and not _isatty(stdin):
        _reconfigure(stdin, encoding="utf-8", errors="replace")


def _isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (ValueError, OSError):  # pragma: no cover - detached stream
        return False


def _reconfigure(stream: TextIO | None, *, encoding: str, errors: str) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:  # pragma: no cover - non-standard stream
        return
    try:
        reconfigure(encoding=encoding, errors=errors)
    except (ValueError, OSError):  # pragma: no cover - already-detached stream
        pass
