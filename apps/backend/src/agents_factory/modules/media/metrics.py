from __future__ import annotations

import math
import re


def word_error_rate(reference: str, transcript: str) -> float:
    expected, actual = (
        re.findall(r"\w+", reference.casefold()),
        re.findall(r"\w+", transcript.casefold()),
    )
    row = list(range(len(actual) + 1))
    for index, word in enumerate(expected, 1):
        next_row = [index]
        for column, other in enumerate(actual, 1):
            next_row.append(
                min(
                    next_row[-1] + 1, row[column] + 1, row[column - 1] + (word != other)
                )
            )
        row = next_row
    return row[-1] / max(1, len(expected))


def latency_percentiles(milliseconds: tuple[float, ...]) -> dict[str, float | None]:
    if any(not math.isfinite(value) or value < 0 for value in milliseconds):
        raise ValueError("invalid latency sample")
    ordered = sorted(milliseconds)
    return {
        f"p{percentile}": ordered[
            max(0, math.ceil(len(ordered) * percentile / 100) - 1)
        ]
        if ordered
        else None
        for percentile in (50, 95)
    }
