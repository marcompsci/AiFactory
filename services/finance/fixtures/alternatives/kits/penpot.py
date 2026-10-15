"""FIXTURE kit for Penpot: SVG-native export, libraries and live collaboration; Figma files need a converter
plugin that is not available offline."""
from kitbase import Library, Session, export_png, export_svg  # noqa: F401


def import_figma(data):
    raise NotImplementedError("Figma files open only through the converter plugin (not available in the sandbox)")


def create_library(name):
    return Library(name)


def open_session():
    return Session()
