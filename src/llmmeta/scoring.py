"""Profile quality aggregation with explicit evidence coverage (spec §13).

Missing evidence is neither failure nor certainty: impute a neutral prior for
the arithmetic, but report coverage and apply a missing-evidence penalty so a
25%-covered candidate never looks as certain as a 100%-covered one.
"""
from __future__ import annotations

from typing import Mapping, Optional


def weighted_quality(
    components: Mapping[str, Optional[float]],
    weights: Mapping[str, float],
    missing_prior: float = 0.5,
    missing_penalty: float = 0.1,
) -> tuple[float, float, dict[str, float]]:
    """Returns (quality, coverage, imputed_components), all clamped to [0,1]."""
    active = {k: float(v) for k, v in weights.items() if float(v) > 0}
    total = sum(active.values())
    if total <= 0:
        raise ValueError("At least one positive weight is required")

    observed_weight = 0.0
    weighted_sum = 0.0
    imputed: dict[str, float] = {}

    for name, weight in active.items():
        value = components.get(name)
        if value is None:
            value = missing_prior
        else:
            observed_weight += weight
        value = min(1.0, max(0.0, float(value)))
        imputed[name] = value
        weighted_sum += weight * value

    coverage = observed_weight / total
    quality = weighted_sum / total - missing_penalty * (1.0 - coverage)
    return min(1.0, max(0.0, quality)), coverage, imputed
