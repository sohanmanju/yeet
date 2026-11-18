"""Terminal geometry and safe, single-line display text."""

from __future__ import annotations

import struct
from shutil import get_terminal_size

from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.data_structures import Size
from prompt_toolkit.utils import get_cwidth

_CONTROLS = {i: chr(0x2400 + i) for i in range(32)} | {127: "␡"}


def single_line(text: str) -> str:
    """Display control characters without altering the underlying filename/path."""
    return text.translate(_CONTROLS)


def terminal_size() -> Size:
    app = get_app_or_none()
    if app is not None and app.is_running:
        return app.output.get_size()
    size = get_terminal_size()
    return Size(rows=size.lines, columns=size.columns)


def content_width() -> int:
    return max(1, terminal_size().columns - 4)


def fit(text: str, width: int, *, align: str = "left") -> str:
    """Fit terminal cells, including wide characters, without breaking a glyph."""
    text = single_line(text)
    width = max(0, width)
    if get_cwidth(text) > width:
        result, used = [], 0
        for char in text:
            cells = get_cwidth(char)
            if used + cells > max(0, width - 1):
                break
            result.append(char)
            used += cells
        text = "".join(result) + ("…" if width else "")
    padding = max(0, width - get_cwidth(text))
    return " " * padding + text if align == "right" else text + " " * padding


def cell_size(output) -> tuple[int, int]:
    """Use terminal pixel geometry when available, otherwise a 1:2 cell."""
    try:
        import fcntl
        import termios

        rows, cols, xpixels, ypixels = struct.unpack(
            "HHHH", fcntl.ioctl(output.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        )
        if rows and cols and xpixels and ypixels:
            return max(3, xpixels // cols), max(3, ypixels // rows)
    except (ImportError, OSError, ValueError, AttributeError):
        pass
    return 10, 20
