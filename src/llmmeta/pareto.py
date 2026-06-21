"""Eligibility filtering + cost-quality Pareto frontier (spec §15)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class Candidate:
    name: str
    quality: float          # higher is better
    cost: float             # lower is better (p95 by default)
    payload: dict[str, Any]


def dominates(a: Candidate, b: Candidate) -> bool:
    return (
        a.quality >= b.quality
        and a.cost <= b.cost
        and (a.quality > b.quality or a.cost < b.cost)
    )


def pareto_frontier(items: list[Candidate]) -> list[Candidate]:
    return [
        x for x in items
        if not any(dominates(y, x) for y in items if y is not x)
    ]


def best_dominator(item: Candidate, frontier: list[Candidate]) -> Optional[Candidate]:
    """A useful frontier candidate that dominates `item` (cheapest such)."""
    doms = [f for f in frontier if dominates(f, item)]
    return min(doms, key=lambda c: c.cost) if doms else None


def filter_eligible(
    candidates: list[Candidate],
    predicates: list[tuple[str, Callable[[Candidate], bool]]],
) -> tuple[list[Candidate], list[dict]]:
    """Apply named predicates. Returns (eligible, exclusions). Each exclusion
    records the first predicate a candidate failed, for honest reporting."""
    eligible: list[Candidate] = []
    exclusions: list[dict] = []
    for c in candidates:
        failed = next((name for name, pred in predicates if not pred(c)), None)
        if failed is None:
            eligible.append(c)
        else:
            exclusions.append({"name": c.name, "reason": failed, "quality": c.quality, "cost": c.cost})
    return eligible, exclusions
