"""Pure Kitty framebuffer transport and worker-owned pixel canvas."""

from __future__ import annotations

import base64
import math
import os
import zlib
from dataclasses import dataclass

from .meter_canvas import BAR_ROWS, HEADROOM_ROWS, BarCanvas, BarModel

PLACEHOLDER = "\U0010eeee"
ROW_MARKS = "\u0305\u030d\u030e\u0310\u0312\u033d\u033e\u033f\u0346\u034a"


def graphics_supported() -> bool:
    if os.environ.get("TMUX") or os.environ.get("STY"):
        return False
    return (
        os.environ.get("TERM_PROGRAM", "").lower() == "ghostty"
        or "kitty" in os.environ.get("TERM", "")
        or bool(os.environ.get("KITTY_WINDOW_ID"))
    )


def kitty_frame(
    rgba: bytes | bytearray,
    image_id: int,
    width: int,
    height: int,
    columns: int,
    rows: int,
    *,
    update: bool = False,
) -> str:
    """Stream a compressed raw RGBA framebuffer, not an encoded image file.

    Kitty calls framebuffer resources images; f=32 selects raw pixels instead
    of f=100 (PNG). U=1 anchors the surface to the TUI's text cells.
    """
    encoded = base64.b64encode(zlib.compress(rgba, 1)).decode("ascii")
    commands = []
    for offset in range(0, len(encoded), 4096):
        chunk = encoded[offset : offset + 4096]
        more = int(offset + 4096 < len(encoded))
        if offset == 0:
            if update:
                # Edit the displayed root frame; preserve its virtual placement.
                # X=1 replaces pixels, including alpha, so shrinking dots leave no trails.
                header = f"a=f,f=32,o=z,s={width},v={height},i={image_id},r=1,X=1,q=2,"
            else:
                header = (
                    f"a=T,f=32,o=z,s={width},v={height},U=1,i={image_id},"
                    f"c={columns},r={rows},q=2,"
                )
        else:
            header = "a=f," if update else ""
        commands.append(f"\x1b_G{header}m={more};{chunk}\x1b\\")
    return "".join(commands)


@dataclass(frozen=True)
class SurfaceGeometry:
    width: int
    height: int
    columns: int
    rows: int
    cell: int

    @classmethod
    def for_terminal(
        cls, columns: int, terminal_rows: int, cw: int, ch: int
    ) -> SurfaceGeometry:
        max_rows = 5 if terminal_rows >= 24 else 3 if terminal_rows >= 18 else 2
        cell = min(cw, max(3, max_rows * ch // (BAR_ROWS + HEADROOM_ROWS)))
        rows = min(
            len(ROW_MARKS), max(1, math.ceil((BAR_ROWS + HEADROOM_ROWS) * cell / ch))
        )
        return cls(columns * cw, rows * ch, columns, rows, cell)


@dataclass(frozen=True)
class SurfaceRequest:
    model: BarModel
    geometry: SurfaceGeometry
    context: str | None


@dataclass(frozen=True)
class RenderedFrame:
    commands: str
    moving: bool


class CanvasWorker:
    """Accessed exclusively by one executor thread; never touches the UI."""

    def __init__(self) -> None:
        self.canvas = BarCanvas()
        self.context: str | None = None

    def render(
        self, request: SurfaceRequest, dt: float, image_id: int, update: bool
    ) -> RenderedFrame:
        if request.context != self.context:
            self.canvas = BarCanvas()
            self.context = request.context
        geometry = request.geometry
        self.canvas.resize(geometry.width, geometry.height, geometry.cell)
        self.canvas.set_model(request.model)
        moving = self.canvas.step(dt)
        commands = kitty_frame(
            self.canvas.rgba_frame(),
            image_id,
            geometry.width,
            geometry.height,
            geometry.columns,
            geometry.rows,
            update=update,
        )
        return RenderedFrame(commands, moving)
