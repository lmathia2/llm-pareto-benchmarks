"""Entity / benchmark identity + proxy-transfer shrinkage (spec §8, §12).

Identity mappings are versioned evidence, not string cleanup. We never merge by
fuzzy similarity alone; normalized names only *propose* aliases for review.
"""
from __future__ import annotations

import re
import unicodedata

# Policy transfer strengths (spec §12). These are policy choices, not constants.
TRANSFER_STRENGTH = {
    "exact": 1.0,
    "exact_system": 1.0,
    "lmarena_exact": 0.95,
    "lmarena_family": 0.75,
    "family_proxy": 0.75,
    "system_to_model_family": 0.80,
    "qfbench_scaffold": 0.80,
    "provider_route_proxy": 0.70,
    "unknown": 0.0,
}


def shrink_to_prior(score: float | None, transfer_strength: float, prior: float = 0.5) -> float | None:
    """transferred = prior + t * (observed - prior)."""
    if score is None:
        return None
    t = min(1.0, max(0.0, transfer_strength))
    return prior + t * (score - prior)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def entity_id(organization: str | None, model_name: str) -> str:
    org = slugify(organization) if organization else "unknown"
    return f"{org}/{slugify(model_name)}"


def benchmark_id(source_id: str, task_key: str, metric: str, generation: str) -> str:
    """Protocol is part of identity. `generation` is usually a retrieval date or
    protocol_version; a change always yields a new benchmark_id."""
    return f"{source_id}/{slugify(task_key)}/{slugify(metric)}/{generation}"
