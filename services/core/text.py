"""Small text helpers for words people read."""
from __future__ import annotations


def plural(n: int, one: str, many: str | None = None) -> str:
    """"1 file", "3 files" (never "3 file(s)"). Pass `many` for irregular words."""
    return f"{n} {one if n == 1 else (many or one + 's')}"
