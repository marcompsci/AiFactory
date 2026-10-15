"""FIXTURE kit for Excalidraw: whiteboard with export and live collaboration; no component libraries or Figma import."""
from kitbase import Session, create_library, export_png, export_svg, import_figma  # noqa: F401


def open_session():
    return Session()
