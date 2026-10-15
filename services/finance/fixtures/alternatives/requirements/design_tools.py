"""The owner's requirements for a design tool, as tests. Each test is one requirement from the cost review."""
import struct

import kit

FRAME = {"name": "Login screen", "width": 390, "height": 844,
         "layers": [{"type": "rect", "x": 0, "y": 0, "w": 390, "h": 120, "fill": "#32d8ff"},
                    {"type": "text", "x": 24, "y": 60, "text": "Welcome back"}]}
FIGMA = b'{"document": {"children": [{"type": "FRAME", "name": "Login screen"}]}}'


def test_svg_export():
    svg = kit.export_svg(FRAME)
    assert svg.startswith("<svg") and 'width="390"' in svg and "Welcome back" in svg and "#32d8ff" in svg


def test_png_export():
    png = kit.export_png(FRAME, scale=2)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", png[16:24]) == (780, 1688)


def test_figma_import():
    doc = kit.import_figma(FIGMA)
    assert doc["frames"][0]["name"] == "Login screen"


def test_shared_libraries():
    lib = kit.create_library("Brand")
    lib.add("Button", {"layers": [{"type": "rect"}]})
    assert lib.use("Button")["layers"]


def test_realtime_collaboration():
    s = kit.open_session()
    s.join("designer")
    s.join("developer")
    s.edit("designer", {"type": "text", "text": "Sign in"})
    assert s.view("developer")["layers"][-1]["text"] == "Sign in"
