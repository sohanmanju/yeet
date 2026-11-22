"""Verify the port against framebuffer hashes from fix-storage's BarCanvas."""

import asyncio
import base64
import hashlib
import io
import re
import zlib

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import FormattedTextControl, Layout, Window
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output

from yeet.ui.application import TerminalApplication
from yeet.ui.meter import Segment, dot_meter
from yeet.ui.meter_canvas import BarCanvas, BarModel, CanvasSegment
from yeet.ui.meter_pixels import PLACEHOLDER, kitty_frame


@pytest.mark.parametrize(
    "scanning,expected",
    [
        (
            False,
            [
                "2f0d7655176f323443f60d6e3e9caeb0eecee81b8aa2f4074227da33c6d42f36",
                "c0ddf5fb70a7232bfc68abe22eb4dac66f2de5f9ffbd1be3c79edcee99daae54",
                "efa7ab3b5cc3342829ebe6c14bbbada8311528eaefc8316a20fcafc8ae9ab2aa",
            ],
        ),
        (
            True,
            [
                "2f0d7655176f323443f60d6e3e9caeb0eecee81b8aa2f4074227da33c6d42f36",
                "da9c0399d404f33334662dc1e96171d6d401726f166d2915904531e986b40ac5",
                "08d10fc6be4eeb3fc527b293909040c3602db21ddf67b3d4ee68fb051ee8f53f",
            ],
        ),
    ],
)
def test_frames_match_original_renderer(scanning, expected):
    canvas = BarCanvas(transparent=False)
    canvas.resize(160, 80, 8)
    canvas.set_model(
        BarModel(
            (
                CanvasSegment("Apps", (59, 130, 246), 0.2),
                CanvasSegment("Developer", (34, 197, 94), 0.3),
            ),
            hover="Apps",
            scanning=scanning,
        )
    )
    frames = []
    for step in range(1, 51):
        canvas.step(0.016)
        if step in (1, 10, 50):
            frames.append(hashlib.sha256(canvas.buffer).hexdigest())
    assert frames == expected


def test_raw_transport_round_trips_frame_in_protocol_chunks():
    # Enough incompressible data to exercise continuation chunks.
    raw = hashlib.shake_256(b"frame").digest(80 * 50 * 4)
    commands = kitty_frame(raw, 42, 80, 50, 8, 3)
    packets = re.findall(r"\x1b_G([^;]+);([^\x1b]+)\x1b\\", commands)
    assert len(packets) > 1
    assert packets[0][0].startswith("a=T,f=32,o=z,s=80,v=50,U=1,i=42,c=8,r=3,q=2,")
    assert all(len(payload) <= 4096 for _, payload in packets)
    assert all(header.endswith("m=1") for header, _ in packets[:-1])
    assert packets[-1][0] == "m=0"
    assert (
        zlib.decompress(base64.b64decode("".join(payload for _, payload in packets)))
        == raw
    )


def test_live_application_presents_updates_and_releases_its_surface(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "ghostty")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    stream = io.StringIO()
    output = Vt100_Output(
        stream,
        lambda: Size(rows=24, columns=80),
        default_color_depth=ColorDepth.TRUE_COLOR,
        enable_cpr=False,
    )

    async def run():
        with create_pipe_input() as pipe:
            keys = KeyBindings()

            @keys.add("q")
            def quit(event):
                event.app.exit()

            app = TerminalApplication(
                layout=Layout(
                    Window(
                        FormattedTextControl(
                            lambda: dot_meter(
                                [Segment("Apps", 40, "#3b82f6")], 100, width=16
                            )
                        )
                    )
                ),
                input=pipe,
                output=output,
                key_bindings=keys,
                color_depth=ColorDepth.TRUE_COLOR,
                full_screen=True,
            )
            task = asyncio.create_task(app.run_async())
            try:
                # Wait for multiple live frames, bounded independently of machine speed.
                for _ in range(100):
                    if stream.getvalue().count("f=32") >= 3:
                        break
                    await asyncio.sleep(0.01)
                pipe.send_text("q")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    task.cancel()

    asyncio.run(run())
    rendered = stream.getvalue()
    assert rendered.count("a=T,f=32") == 1
    assert rendered.count("a=f,f=32") >= 2
    assert "\x1b[?2026h" in rendered
    assert "\x1b[?2026l" in rendered
    assert PLACEHOLDER in rendered
    assert "a=d,d=I" in rendered
    assert "f=100" not in rendered


def test_canvas_background_is_transparent():
    canvas = BarCanvas()
    canvas.resize(160, 80, 8)
    canvas.set_model(BarModel((CanvasSegment("Apps", (59, 130, 246), 0.5),)))
    canvas.step(0.1)
    frame = canvas.rgba_frame()
    assert set(frame[3 : 160 * 4 : 4]) == {0}
    assert any(0 < alpha < 255 for alpha in frame[3::4])
    assert any(
        max(frame[i : i + 3]) > frame[i + 3]
        for i in range(0, len(frame), 4)
        if 0 < frame[i + 3] < 255
    )


def test_update_edits_existing_frame_and_replaces_transparent_pixels():
    raw = hashlib.shake_256(b"update").digest(80 * 50 * 4)
    commands = kitty_frame(raw, 42, 80, 50, 8, 3, update=True)
    packets = re.findall(r"\x1b_G([^;]+);([^\x1b]+)\x1b\\", commands)
    assert len(packets) > 1
    assert packets[0][0].startswith("a=f,f=32,o=z,s=80,v=50,i=42,r=1,X=1,q=2,")
    assert all(header.startswith("a=f,") for header, _ in packets)
    assert packets[-1][0] == "a=f,m=0"
    assert "a=T" not in commands
    assert (
        zlib.decompress(base64.b64decode("".join(payload for _, payload in packets)))
        == raw
    )
