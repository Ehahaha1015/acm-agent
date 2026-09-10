"""Layout invariants for the browser UI.

These assertions exist because of a real reported bug: the page could not be scrolled at
all. ``.app-shell`` is a grid whose only row was content-sized, so ``.chat-panel``
(``height: 100%``) resolved against its own content and grew to ~4000px inside a
``overflow: hidden`` shell. ``.messages`` therefore never became a scroller, the composer
ended up far below the viewport, and everything past the first screen was unreachable.

A browser regression test would be better, but it cannot run in CI; instead these cheap
assertions fail loudly if anyone removes the declarations that keep the shell bounded to
one viewport and ``.messages`` the single vertical scroller.
"""

from __future__ import annotations

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[1] / "src" / "acm_agent" / "api" / "web" / "style.css"
).read_text(encoding="utf-8")


def declarations(selector: str) -> str:
    """Return the declaration block of the first top-level rule for ``selector``."""
    match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", CSS)
    assert match, f"style.css has no rule for {selector!r}"
    return " ".join(match.group(1).split())


def test_shell_is_bounded_to_one_viewport():
    shell = declarations(".app-shell")
    assert "height: 100dvh" in shell or "height: 100vh" in shell, shell
    assert "overflow: hidden" in shell, shell


def test_shell_row_is_not_sized_by_content():
    shell = declarations(".app-shell")
    assert "grid-template-rows" in shell, (
        "without an explicit row the implicit auto row is sized from content, which is "
        "what made .messages unscrollable"
    )
    rows = re.search(r"grid-template-rows:([^;]+)", shell)
    assert rows and rows.group(1).strip() != "auto", shell


def test_chat_panel_is_a_bounded_grid_with_a_shrinkable_messages_row():
    panel = declarations(".chat-panel")
    assert "min-height: 0" in panel, panel
    rows = re.search(r"grid-template-rows:([^;]+)", panel)
    assert rows, panel
    assert "minmax(0, 1fr)" in rows.group(1), (
        "the middle row must be allowed to shrink below its content height"
    )


def test_messages_is_the_only_vertical_scroller():
    messages = declarations(".messages")
    assert "overflow-y: auto" in messages, messages
    assert "min-height: 0" in messages, messages


def test_mobile_layout_avoids_viewport_width_units():
    block = re.search(r"@media \(max-width: 760px\) \{(.*)\n\}", CSS, re.DOTALL)
    assert block, "the mobile breakpoint is missing"
    assert "100vw" not in block.group(1), (
        "100vw includes the scrollbar/URL-bar width and causes horizontal overflow; "
        "use percentages inside the full-width panel"
    )
