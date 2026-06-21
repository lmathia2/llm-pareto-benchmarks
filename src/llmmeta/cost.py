"""Workload cost model (spec §14). Cost is workload-specific: token mix,
retries, fixed tool costs, and a configurable p95 risk basis."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Workload:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    calls: int = 1
    retry_multiplier: float = 1.0
    fixed_tool_cost_usd: float = 0.0


def estimate_cost(
    workload: Workload,
    input_price: float | None = None,
    output_price: float | None = None,
    cached_input_price: float | None = None,
    cache_write_price: float | None = None,
    blended_price: float | None = None,
    p95_token_multiplier: float = 1.35,
    p95_tool_multiplier: float = 1.15,
) -> tuple[float, float, str]:
    """Returns (expected_cost, p95_cost, pricing_basis)."""
    retry = max(0.0, workload.retry_multiplier)
    I = workload.input_tokens * retry
    O = (workload.output_tokens + workload.reasoning_tokens) * retry
    C = workload.cached_input_tokens * retry
    W = workload.cache_write_tokens * retry

    if input_price is not None and output_price is not None:
        token_cost = (
            I * input_price
            + O * output_price
            + C * (cached_input_price if cached_input_price is not None else input_price)
            + W * (cache_write_price if cache_write_price is not None else input_price)
        ) / 1_000_000
        pricing_basis = "separate input/output token prices"
    elif blended_price is not None:
        token_cost = (I + O + C + W) * blended_price / 1_000_000
        pricing_basis = "published blended token price"
    else:
        raise ValueError("No usable price fields")

    fixed = max(0.0, workload.fixed_tool_cost_usd)
    expected = token_cost + fixed
    p95 = token_cost * max(1.0, p95_token_multiplier) + fixed * max(1.0, p95_tool_multiplier)
    return expected, p95, pricing_basis
