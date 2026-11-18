"""Live port of fix-storage's BarCanvas (see THIRD_PARTY_NOTICES.md).

The canvas owns a raw RGBA framebuffer. Nothing is rendered through a font,
encoded as a PNG, or read from an image file.
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from functools import lru_cache

WHITE = (255, 255, 255)
BAR_ROWS = 7
HEADROOM_ROWS = 3


@lru_cache(maxsize=65536)
def _straight_pixel(pixel: int) -> int:
    """Repeated dot/wash pixels share their straight-alpha conversion."""
    alpha = pixel >> 24
    return (
        min(255, (pixel & 255) * 255 // alpha)
        | min(255, ((pixel >> 8) & 255) * 255 // alpha) << 8
        | min(255, ((pixel >> 16) & 255) * 255 // alpha) << 16
        | alpha << 24
    )


def dot_hash(a: int, b: int) -> float:
    """Match JavaScript Math.imul and unsigned shifts, including overflow."""
    h = (((a + 374761393) * 668265263) & 0xFFFFFFFF) ^ (
        ((b + 1274126177) * 2246822519) & 0xFFFFFFFF
    )
    h = ((h ^ (h >> 13)) * 3266489917) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFFFF) / 4294967296


@dataclass(frozen=True)
class CanvasSegment:
    id: str
    color: tuple[int, int, int]
    fraction: float


@dataclass(frozen=True)
class BarModel:
    segments: tuple[CanvasSegment, ...] = ()
    hover: str | None = None
    scanning: bool = False
    clearing: str | None = None


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    span: float
    color: tuple[int, int, int]


@lru_cache(maxsize=64)
def _dot_mask(radius: float, fx: float, fy: float, glowing: bool):
    """Cache geometry only; light and twinkle are recomputed every frame."""
    reach = radius * 3.2 if glowing else radius + 1
    samples = []
    for y in range(math.floor(fy - reach), math.ceil(fy + reach) + 1):
        for x in range(math.floor(fx - reach), math.ceil(fx + reach) + 1):
            distance = math.hypot(x + 0.5 - fx, y + 0.5 - fy)
            coverage = min(1, max(0, radius + 0.5 - distance))
            halo = math.exp(-((distance / (radius * 1.6)) ** 2)) if glowing else 0
            if coverage or halo > 0.004:
                samples.append((x, y, coverage, halo))
    return tuple(samples)


class BarCanvas:
    def __init__(self, *, transparent: bool = True):
        self.transparent = transparent
        self.width = self.height = 0
        self.cell = 8
        self.buffer = bytearray()
        self.shown: dict[str, float] = {}
        self.level: dict[str, float] = {}
        self.particles: list[Particle] = []
        self.placed = []
        self.time = self.edge = 0.0
        self.model = BarModel()

    @property
    def top(self):
        return self.height - BAR_ROWS * self.cell

    def resize(self, width: int, height: int, cell: int):
        width, height, cell = max(1, width), max(1, height), max(3, cell)
        if (width, height, cell) != (self.width, self.height, self.cell):
            self.width, self.height, self.cell = width, height, cell
            self.buffer = bytearray(width * height * 4)

    def set_model(self, model: BarModel):
        self.model = model
        ids = {segment.id for segment in model.segments}
        self.shown = {key: value for key, value in self.shown.items() if key in ids}
        self.level = {key: value for key, value in self.level.items() if key in ids}

    def hit(self, x: float, y: float) -> str | None:
        if y < self.top or y >= self.height:
            return None
        return next((id for id, x0, x1, _, _ in self.placed if x0 <= x < x1), None)

    def step(self, dt: float) -> bool:
        if not self.width:
            return False
        dt = min(max(0, dt), 0.1)
        self.time += dt
        model = self.model
        moving = model.scanning or model.clearing is not None
        ease, fade = min(1, dt * 9), min(1, dt * 12)
        cursor = 0.0
        for segment in model.segments:
            previous = self.shown.get(segment.id, 0)
            target = previous + (segment.fraction - previous) * ease
            if abs(segment.fraction - target) < 0.00005:
                target = segment.fraction
            else:
                moving = True
            self.shown[segment.id] = target
            wanted = (
                1 if model.hover is None else 1.15 if model.hover == segment.id else 0.4
            )
            current = self.level.get(segment.id, 1)
            level = current + (wanted - current) * fade
            if abs(wanted - level) < 0.01:
                level = wanted
            else:
                moving = True
            self.level[segment.id] = level
            if model.clearing == segment.id and target < previous:
                self._shed(
                    (cursor + previous) * self.width,
                    (previous - target) * self.width,
                    segment.color,
                )
            cursor += target
        wanted_edge = 1 if model.scanning else 0
        self.edge += (wanted_edge - self.edge) * min(1, dt * 6)
        moving |= abs(wanted_edge - self.edge) > 0.01
        self._advance(dt)
        self._draw()
        return moving or bool(self.particles)

    def _shed(self, x, lost, color):
        scale = self.cell / 8
        count = min(48, math.ceil(lost / self.cell * BAR_ROWS * 0.9))
        for _ in range(count):
            span = 0.45 + random.random() * 0.75
            self.particles.append(
                Particle(
                    x - random.random() * max(lost, self.cell),
                    self.top + random.random() * BAR_ROWS * self.cell,
                    (10 + random.random() * 70) * scale,
                    -(30 + random.random() * 130) * scale,
                    span,
                    span,
                    WHITE if random.random() < 0.35 else color,
                )
            )
        self.particles = self.particles[-900:]

    def _advance(self, dt):
        kept = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy -= 60 * (self.cell / 8) * dt
            p.vx *= 1 - min(1, dt * 1.5)
            p.x += p.vx * dt
            p.y += p.vy * dt
            kept.append(p)
        self.particles = kept

    def _blend(self, x, y, color, alpha):
        if alpha <= 0 or not (0 <= x < self.width and 0 <= y < self.height):
            return
        i = (y * self.width + x) * 4
        alpha = min(1, alpha)
        b = self.buffer
        b[i] = int(b[i] + (color[0] - b[i]) * alpha)
        b[i + 1] = int(b[i + 1] + (color[1] - b[i + 1]) * alpha)
        b[i + 2] = int(b[i + 2] + (color[2] - b[i + 2]) * alpha)
        if self.transparent:
            b[i + 3] = min(255, math.floor(b[i + 3] + (255 - b[i + 3]) * alpha + 0.5))

    def _block(self, x0, x1, color, level):
        """Original rounded wash; bulk-fill its flat interior in native code."""
        width, height = x1 - x0, self.height - self.top
        if width < 1 or height < 1:
            return
        radius = min(self.cell * 0.45, width / 2, height / 2)
        cx, cy = (x0 + x1) / 2, (self.top + self.height) / 2
        hx, hy = width / 2 - radius, height / 2 - radius
        xa, xb = max(0, math.floor(x0)), min(self.width, math.ceil(x1))
        flat = bytes(
            (
                *[int(channel * 0.07 * level) for channel in color],
                math.floor(255 * 0.07 * level + 0.5) if self.transparent else 255,
            )
        )
        left_end = min(xb, math.ceil(x0 + radius) + 1)
        right_start = max(left_end, math.floor(x1 - radius) - 1)
        corners = tuple(range(xa, left_end)) + tuple(range(right_start, xb))
        for y in range(max(0, self.top), self.height):
            start = (y * self.width + left_end) * 4
            self.buffer[start : start + (right_start - left_end) * 4] = flat * (
                right_start - left_end
            )
            qy = abs(y + 0.5 - cy) - hy
            # Only the rounded corners and fractional edges differ from the flat fill.
            for x in corners:
                qx = abs(x + 0.5 - cx) - hx
                distance = (
                    math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
                )
                coverage = min(1, max(0, 0.5 - distance))
                self._blend(x, y, color, coverage * 0.07 * level)

    def _dot(self, cx, cy, radius, color, alpha, glow=0):
        ix, iy = math.floor(cx), math.floor(cy)
        for dx, dy, coverage, halo in _dot_mask(radius, cx - ix, cy - iy, glow > 0):
            a = coverage * alpha
            if glow:
                a += glow * halo * (1 - a)
            if a > 0.004:
                self._blend(ix + dx, iy + dy, color, a)

    def rgba_frame(self) -> bytes | bytearray:
        """Kitty expects straight alpha; our blending buffer is premultiplied."""
        if not self.transparent:
            return self.buffer
        result = bytearray(self.buffer)
        if sys.byteorder == "little":
            pixels = memoryview(result).cast("I")
            convert = _straight_pixel
            for i, pixel in enumerate(pixels):
                if 0 < pixel >> 24 < 255:
                    pixels[i] = convert(pixel)
            return result
        for i in range(0, len(result), 4):
            alpha = result[i + 3]
            if 0 < alpha < 255:
                for channel in range(3):
                    result[i + channel] = min(255, result[i + channel] * 255 // alpha)
        return result

    def _draw(self):
        self.buffer[:] = (b"\0\0\0\0" if self.transparent else b"\0\0\0\xff") * (
            self.width * self.height
        )
        self.placed = []
        x = 0.0
        for segment in self.model.segments:
            width = self.shown.get(segment.id, 0) * self.width
            if width >= 0.5:
                self.placed.append(
                    (
                        segment.id,
                        x,
                        x + width,
                        segment.color,
                        self.level.get(segment.id, 1),
                    )
                )
            x += width
        filled = x
        for _, x0, x1, color, level in self.placed:
            self._block(x0, x1, color, level)
        columns = self.width // self.cell
        offset = (self.width - columns * self.cell) / 2
        radius, inset = max(1, self.cell * 0.24), self.cell * 0.3
        index = 0
        for column in range(columns):
            cx = offset + column * self.cell + self.cell / 2
            while index < len(self.placed) and cx >= self.placed[index][2]:
                index += 1
            segment = self.placed[index] if index < len(self.placed) else None
            within = (
                segment is not None and segment[1] + inset <= cx <= segment[2] - inset
            )
            lead = (
                max(0, 1 - (filled - cx) / (self.cell * 3)) * self.edge
                if self.edge > 0 and cx <= filled
                else 0
            )
            burn = (
                max(0, 1 - (segment[2] - cx) / (self.cell * 2.5))
                if within and self.model.clearing == segment[0]
                else 0
            )
            hot = max(lead, burn)
            for row in range(BAR_ROWS):
                cy = self.top + row * self.cell + self.cell / 2
                if not within:
                    if segment is None or cx > segment[2] or cx < segment[1]:
                        self._dot(cx, cy, radius * 0.8, WHITE, 0.05)
                    continue
                color, level = segment[3:]
                kind, phase = dot_hash(column, row), dot_hash(row + 101, column + 17)
                twinkle = 0.72 + 0.28 * math.sin(
                    self.time * (0.8 + phase * 2.6) + phase * 40
                )
                if hot > 0 and kind < 0.35 + hot * 0.65:
                    self._dot(cx, cy, radius, WHITE, min(1, 0.6 + hot * 0.4), 0.3 * hot)
                elif kind < 0.5:
                    self._dot(cx, cy, radius, color, 0.45 * twinkle * level)
                elif kind < 0.86:
                    self._dot(cx, cy, radius, color, 0.95 * twinkle * level)
                else:
                    self._dot(
                        cx,
                        cy,
                        radius,
                        WHITE,
                        min(1, 0.95 * twinkle * level),
                        0.22 * twinkle * min(1, level),
                    )
        size = max(1, math.floor(self.cell / 4 + 0.5))
        for p in self.particles:
            alpha = min(1, p.life / p.span * 1.4)
            px, py = math.floor(p.x + 0.5), math.floor(p.y + 0.5)
            for dy in range(size):
                for dx in range(size):
                    self._blend(px + dx, py + dy, p.color, alpha)
