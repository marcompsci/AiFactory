"""FIXTURE compatibility kit base: real, runnable code that models what each candidate's documentation says it can
do. The sandbox evaluates candidates against the owner's requirements using these kits. It is not the vendor's
software (no downloaded software is executed), and results are labeled that way everywhere."""
import struct
import zlib


def _escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def export_svg(frame):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{frame["width"]}" height="{frame["height"]}">']
    for layer in frame["layers"]:
        if layer["type"] == "rect":
            parts.append(f'<rect x="{layer["x"]}" y="{layer["y"]}" width="{layer["w"]}" height="{layer["h"]}" fill="{layer["fill"]}"/>')
        elif layer["type"] == "text":
            parts.append(f'<text x="{layer["x"]}" y="{layer["y"]}">{_escape(layer["text"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def export_png(frame, scale=1):
    """A valid (blank) PNG of the frame at the requested scale."""
    w, h = int(frame["width"] * scale), int(frame["height"] * scale)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 1)) + _chunk(b"IEND", b""))


def import_figma(data):
    raise NotImplementedError("this candidate cannot open Figma files")


class Library:
    def __init__(self, name):
        self.name, self.components = name, {}

    def add(self, name, frame):
        self.components[name] = frame

    def use(self, name):
        return dict(self.components[name])


def create_library(name):
    raise NotImplementedError("this candidate has no shared component libraries")


class Session:
    def __init__(self):
        self.doc, self.members = {"layers": []}, set()

    def join(self, who):
        self.members.add(who)

    def edit(self, who, layer):
        if who not in self.members:
            raise PermissionError(who)
        self.doc["layers"].append(layer)

    def view(self, who):
        return self.doc if who in self.members else None


def open_session():
    raise NotImplementedError("this candidate has no real-time collaboration")
