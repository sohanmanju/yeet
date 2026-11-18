"""Shared, cell-aware headings and keyboard hints for interactive screens."""

from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.utils import get_cwidth

from .geometry import content_width, fit


def screen_title(title: str) -> FormattedText:
    width = content_width()
    if width < 40:
        return FormattedText(
            [("class:title", "  " + fit(title, width).rstrip() + "\n")]
        )
    return FormattedText(
        [
            ("class:brand", "  yeet"),
            ("class:dim", "  /  "),
            ("class:title", fit(title, width - 10).rstrip() + "\n"),
        ]
    )


def key_hints(hints: list[tuple[str, str]]) -> FormattedText:
    """Keep complete hints in priority order; never leave a clipped key label."""
    fragments = [("", "  ")]
    used = 0
    for key, label in hints:
        length = get_cwidth(key + " " + label) + (3 if used else 0)
        if used + length > content_width():
            continue
        if used:
            fragments.append(("class:dim", " · "))
        fragments.extend([("class:key", key), ("class:help", " " + label)])
        used += length
    fragments.append(("", "\n"))
    return FormattedText(fragments)
