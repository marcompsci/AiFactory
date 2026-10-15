"""FIXTURE kit for Akira (alpha): exports exist but PNG scaling is not honored, matching its early state."""
from kitbase import create_library, export_svg, import_figma, open_session  # noqa: F401
from kitbase import export_png as _png


def export_png(frame, scale=1):
    return _png(frame, 1)  # ignores the scale
