from __future__ import annotations

from typing import Sequence


def mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean() of empty sequence")
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median() of empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def clamp(value: float, low: float, high: float) -> float:
    if low > high:
        raise ValueError("low must be <= high")
    return max(low, min(value, high))
