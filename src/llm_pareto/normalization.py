"""Benchmark-local normalization (spec §11).

Normalize ONLY within one exact benchmark_id cohort. Never across datasets,
protocol generations, judges, or publication pools. The tie-aware empirical
CDF is monotone and unit-free; it deliberately does not claim equal cardinal
distance across benchmarks.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

METHOD_VERSION = "tie-aware-ecdf-v1"


def tie_aware_ecdf(points: Iterable[tuple], direction: str = "higher_is_better") -> list[dict]:
    """points: [(key, raw_score), ...]. Returns rows with normalized_score in [0,1]
    and competition rank (1 = best). Ties share the averaged position."""
    rows = list(points)
    if not rows:
        return []

    adjusted = [
        (key, raw if direction == "higher_is_better" else -raw, raw)
        for key, raw in rows
    ]
    adjusted.sort(key=lambda r: (r[1], r[0]))
    n = len(adjusted)

    positions: dict[float, list[int]] = defaultdict(list)
    for idx, (_, value, _) in enumerate(adjusted):
        positions[value].append(idx)

    normalized_by_value = {
        value: 0.5 if n == 1 else (sum(idxs) / len(idxs)) / (n - 1)
        for value, idxs in positions.items()
    }

    best_first = sorted(adjusted, key=lambda r: (-r[1], r[0]))
    rank_by_key: dict = {}
    previous = None
    current_rank = 0
    for idx, (key, value, _) in enumerate(best_first, start=1):
        if previous is None or value != previous:
            current_rank = idx
            previous = value
        rank_by_key[key] = current_rank

    return [
        {
            "key": key,
            "raw_score": raw,
            "normalized_score": normalized_by_value[value],
            "rank": rank_by_key[key],
            "cohort_size": n,
        }
        for key, value, raw in adjusted
    ]
