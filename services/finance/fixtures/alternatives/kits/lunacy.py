"""FIXTURE kit for Lunacy: UI design with components; no Figma import, no live collaboration in this kit."""
from kitbase import Library, export_png, export_svg, import_figma, open_session  # noqa: F401


def create_library(name):
    return Library(name)
